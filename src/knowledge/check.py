"""Source-bounded medication flags; no ingredient inference or prescription changes."""

import json
import math
from pathlib import Path

DEFAULT_RULES = Path(__file__).with_name("rules") / "medication-reference-v1.json"


def load_rules(path=None):
    """Load reference rules, including disabled drafts for explicit accounting."""
    value = json.loads(Path(path or DEFAULT_RULES).read_text(encoding="utf-8"))
    return value["rules"] if isinstance(value, dict) else value


def evaluate_condition(node, context):
    """Return (True/False/None, unresolved fields); None means unknown, never false."""
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        if not node[key]:
            raise ValueError("Empty logical expression")
        children = [evaluate_condition(child, context) for child in node[key]]
        decisive = False if key == "all" else True
        if any(value is decisive for value, _ in children):
            return decisive, []
        missing = sorted({field for _, fields in children for field in fields})
        if any(value is None for value, _ in children):
            return None, missing
        return not decisive, []
    if "not" in node:
        value, missing = evaluate_condition(node["not"], context)
        return (None if value is None else not value), missing
    field, op, expected = node["field"], node["op"], node["value"]
    value = context.get(field)
    # The measurement domain was fixed in the predicate definition before extraction.
    # It is input validation, independent of a model-generated clinical threshold.
    if field == "egfr_ml_min_1_73m2" and not (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0):
        return None, ["context." + field]
    if isinstance(expected, bool):
        valid = isinstance(value, bool)
    elif isinstance(expected, (int, float)):
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value >= node.get("minimum", -math.inf))
    else:
        raise ValueError("Only Boolean and numeric predicates are supported")
    if not valid:
        return None, ["context." + field]
    if op == "eq":
        return value == expected, []
    if op == "lt" and not isinstance(expected, bool):
        return value < expected, []
    raise ValueError("Unsupported predicate operator: " + op)


def check(case, recommendation, rules=None):
    """Implement CheckReport. Counts refer to candidate-rule evaluations, not patients."""
    rules = load_rules() if rules is None else rules
    report = {key: case.get(key) for key in ("contract_version", "data_kind", "case_id")}
    report.update(execution="synthetic_fixture" if recommendation.get("execution") == "synthetic_fixture"
                  else "rule_check", status="not_checked", applied_rules=[], findings=[],
                  missing_fields=[], unchecked_reasons=[], coverage={
                      "checked_rule_count": 0, "pending_rule_count": 0,
                      "checked_candidate_count": 0, "candidate_count": 0,
                      "scope": "Only loaded, source-reviewed rule scopes; counts are candidate-rule evaluations. "
                               "No clinical safety conclusion, no automatic candidate removal."})
    reasons = report["unchecked_reasons"]
    for field in ("contract_version", "data_kind", "case_id"):
        if case.get(field) is None or case.get(field) != recommendation.get(field):
            reasons.append({"code": "contract_mismatch", "field": field})
    if case.get("contract_version") != "0.1-draft" or case.get("data_kind") not in {"synthetic", "restricted"}:
        reasons.append({"code": "unsupported_contract", "field": "contract_version/data_kind"})
    if recommendation.get("status") != "ok":
        reasons.append({"code": "recommendation_not_ok", "status": recommendation.get("status")})
    if reasons:
        return report
    candidates = recommendation.get("candidates")
    if not isinstance(candidates, list):
        reasons.append({"code": "invalid_candidates"})
        return report
    report["coverage"]["candidate_count"] = len(candidates)
    active = []
    for rule in rules:
        if rule.get("review_status") != "reviewed":
            reasons.append({"code": "rule_disabled", "rule_id": rule.get("rule_id"),
                            "review_status": rule.get("review_status")})
        elif rule.get("origin") == "synthetic_fixture" and case["data_kind"] != "synthetic":
            reasons.append({"code": "synthetic_rule_restricted_input", "rule_id": rule["rule_id"]})
        elif rule.get("kind") != "medication" or rule.get("action") != "flag":
            reasons.append({"code": "unsupported_rule_kind_or_action", "rule_id": rule.get("rule_id")})
        else:
            active.append(rule)
            if rule.get("origin") == "synthetic_fixture":
                report["execution"] = "synthetic_fixture"
    if not active:
        reasons.append({"code": "no_reviewed_medication_rules"})
    checked_candidates = set()
    applied = set()
    context = case.get("context") if isinstance(case.get("context"), dict) else {}
    for index, candidate in enumerate(candidates):
        drug = candidate.get("drug", {}) if isinstance(candidate, dict) else {}
        if not isinstance(drug, dict):
            drug = {}
        matched = False
        for rule in active:
            selector = rule["selector"]
            exact = drug.get("system") == selector["system"] and drug.get("code") == selector["code"]
            broad = drug.get("system") == "ATC3" and drug.get("code") in rule.get("possible_atc3", [])
            if not (exact or broad):
                continue
            matched = True
            fields = []
            if broad:
                fields = [f"candidates[{index}].drug.exact_ingredient_identity"]
            else:
                scope_mismatch = [name for name in ("route", "dose_form")
                                  if drug.get(name) is not None and drug[name] != selector[name]]
                if scope_mismatch:
                    reasons.append({"code": "outside_label_scope", "candidate_index": index,
                                    "rule_id": rule["rule_id"], "fields": scope_mismatch})
                    continue
                fields = [f"candidates[{index}].drug.{name}" for name in ("route", "dose_form")
                          if drug.get(name) is None]
            if fields:
                value = None
            else:
                value, fields = evaluate_condition(rule["condition"], context)
            if value is None:
                report["coverage"]["pending_rule_count"] += 1
                report["missing_fields"].append({"rule_id": rule["rule_id"], "candidate_index": index,
                                                  "fields": fields,
                                                  "reason": "ingredient_identity_unknown" if broad
                                                  else "missing_or_invalid_required_fact"})
                continue
            report["coverage"]["checked_rule_count"] += 1
            checked_candidates.add(index)
            identifier = (rule["rule_id"], rule["version"])
            if identifier not in applied:
                report["applied_rules"].append({"rule_id": identifier[0], "version": identifier[1]})
                applied.add(identifier)
            if value:
                report["findings"].append({"rule_id": rule["rule_id"], "version": rule["version"],
                    "candidate_index": index, "drug": dict(drug), "action": "flag", "statement": rule["statement"],
                    "known_facts": {key: context[key] for key in rule["required_fields"] if context.get(key) is not None},
                    "source": rule["source"], "evidence": rule["evidence"]})
        if not matched:
            reasons.append({"code": "candidate_not_covered", "candidate_index": index, "drug": dict(drug)})
    report["coverage"]["checked_candidate_count"] = len(checked_candidates)
    if report["findings"]:
        report["status"] = "issues_found"
    elif report["coverage"]["pending_rule_count"]:
        report["status"] = "insufficient_information"
    elif report["coverage"]["checked_rule_count"]:
        report["status"] = "checked"
    return report
