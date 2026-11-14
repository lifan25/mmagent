"""Source-bounded medication flags; no ingredient inference or prescription changes."""

import json
import math
from itertools import combinations
from pathlib import Path

DEFAULT_RULES = Path(__file__).with_name("rules") / "medication-reference-v1.json"
DEFAULT_PRODUCTS = Path(__file__).with_name("rules") / "rxnorm-rule-products-v1.json"


def load_rules(path=None):
    """Load reference rules, including disabled drafts for explicit accounting."""
    value = json.loads(Path(path or DEFAULT_RULES).read_text(encoding="utf-8"))
    return value["rules"] if isinstance(value, dict) else value


def load_product_metadata(path=None):
    """Read a frozen public NLM identity snapshot; never infer from patient targets."""
    return json.loads(Path(path or DEFAULT_PRODUCTS).read_text(encoding="utf-8"))


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


def _check_candidate_pairs(candidates, rules, products, known_source_codes, report):
    """Flag source-scoped co-selection, without claiming actual concurrent use."""
    coverage = report["pair_coverage"] = {
        "candidate_pair_count": len(candidates) * (len(candidates)-1) // 2,
        "checked_pair_count": 0, "pending_pair_count": 0, "uncovered_pair_count": 0,
        "scope": "Unordered candidate-pair-rule assessments, separate from patient-condition checks. "
                 "A matched pair needs review of intended concurrent use; unmatched is not safe."}
    applied = set()

    def membership(candidate, selector, side):
        drug = candidate.get("drug", {}) if isinstance(candidate, dict) else {}
        if (isinstance(drug, dict) and drug.get("system") == "RxNorm"
                and drug.get("code") in known_source_codes
                and drug["code"] not in selector[side]["allowed_product_rxcuis"]):
            return False  # A documented code outside this exact scope; no identity guess.
        product = products.get(drug.get("code")) if isinstance(drug, dict) and drug.get("system") == "RxNorm" else None
        identity = product.get("identity", {}) if isinstance(product, dict) else {}
        if identity.get("status") != "resolved" or not identity.get("ingredients_complete"):
            return None
        group = selector[side]
        if drug.get("code") not in group["allowed_product_rxcuis"]:
            return False
        if not set(identity.get("ingredient_rxcuis", [])) & set(group["ingredient_rxcuis"]):
            return False
        if identity.get("route") is None or identity.get("dose_form_rxcui") is None:
            return None
        return (identity["route"] == selector["route"]
                and identity["dose_form_rxcui"] in selector["allowed_dose_form_rxcuis"])

    def both(left, right):
        return False if left is False or right is False else (None if left is None or right is None else True)

    for a, b in combinations(range(len(candidates)), 2):
        for rule in rules:
            selector = rule["selector"]
            values = [both(membership(candidates[a], selector, "left"), membership(candidates[b], selector, "right")),
                      both(membership(candidates[b], selector, "left"), membership(candidates[a], selector, "right"))]
            outcome = True if True in values else (None if None in values else False)
            if outcome is False:
                coverage["uncovered_pair_count"] += 1
                continue
            if outcome is None:
                coverage["pending_pair_count"] += 1
                report["missing_fields"].append({"rule_id":rule["rule_id"], "candidate_indices":[a,b],
                    "fields":[f"candidates[{i}].drug.frozen_identity_and_scope" for i in (a,b)],
                    "reason":"candidate_pair_identity_or_scope_unknown"})
                continue
            coverage["checked_pair_count"] += 1
            key = (rule["rule_id"], rule["version"])
            if key not in applied:
                report["applied_rules"].append({"rule_id":key[0], "version":key[1],
                                                "evaluation_unit":"candidate_pair"})
                applied.add(key)
            drugs = [dict(candidates[i]["drug"]) for i in (a,b)]
            report["findings"].append({"rule_id":rule["rule_id"], "version":rule["version"],
                "candidate_indices":[a,b], "drugs":drugs, "action":"flag",
                "classification":rule["classification"], "evaluation_unit":"candidate_pair",
                "statement":rule["statement"], "known_facts":{"co_selected_candidates":True},
                "actual_concurrent_use":"unknown", "source":rule["source"], "evidence":rule["evidence"],
                "scope_evidence":rule.get("scope_evidence", []),
                "identities":[products[d["code"]]["identity"] for d in drugs],
                "identity_sources":[products[d["code"]]["sources"] for d in drugs]})


def check(case, recommendation, rules=None, product_metadata=None):
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
        elif rule.get("kind") not in {"medication", "medication_pair"} or rule.get("action") != "flag":
            reasons.append({"code": "unsupported_rule_kind_or_action", "rule_id": rule.get("rule_id")})
        else:
            active.append(rule)
            if rule.get("origin") == "synthetic_fixture":
                report["execution"] = "synthetic_fixture"
    if not active:
        reasons.append({"code": "no_reviewed_medication_rules"})
    pair_rules = [rule for rule in active if rule["kind"] == "medication_pair"]
    use_products = any(rule["selector"]["system"] in {"RxNormIngredient", "RxNormIngredientPair"} for rule in active)
    if use_products:
        product_metadata = load_product_metadata() if product_metadata is None else product_metadata
        products = product_metadata["products"]
        report["coverage"]["product_metadata_version"] = product_metadata["version"]
        known_source_codes = set(product_metadata.get("known_source_rxcuis", []))
        explicit_scope_codes = set()
        for rule in active:
            selector = rule["selector"]
            if selector["system"] == "RxNormIngredientPair":
                explicit_scope_codes.update(selector["left"]["allowed_product_rxcuis"])
                explicit_scope_codes.update(selector["right"]["allowed_product_rxcuis"])
            elif "allowed_product_rxcuis" in selector:
                explicit_scope_codes.update(selector["allowed_product_rxcuis"])
            else:
                explicit_scope_codes = None
                break  # Older ingredient-wide packages are not silently narrowed.
    checked_candidates = set()
    applied = set()
    context = case.get("context") if isinstance(case.get("context"), dict) else {}
    for index, candidate in enumerate(candidates):
        drug = candidate.get("drug", {}) if isinstance(candidate, dict) else {}
        if not isinstance(drug, dict):
            drug = {}
        identity = None
        product = None
        if use_products and drug.get("system") == "RxNorm":
            if (explicit_scope_codes is not None and drug.get("code") in known_source_codes
                    and drug["code"] not in explicit_scope_codes):
                reasons.append({"code":"outside_reviewed_product_scope", "candidate_index":index,
                                "drug":dict(drug), "metadata_version":product_metadata["version"]})
                continue
            product = products.get(drug.get("code"))
            identity = product.get("identity") if isinstance(product, dict) else None
            if not identity or identity.get("status") != "resolved" or not identity.get("ingredient_rxcuis"):
                reasons.append({"code": "product_metadata_missing", "candidate_index": index,
                                "drug": dict(drug), "metadata_version": product_metadata["version"]})
                report["missing_fields"].append({"candidate_index": index,
                    "fields": [f"candidates[{index}].drug.identity"],
                    "reason": "frozen_product_identity_unavailable"})
                continue
        matched = False
        for rule in (rule for rule in active if rule["kind"] == "medication"):
            selector = rule["selector"]
            product_rule = selector["system"] == "RxNormIngredient"
            if product_rule:
                exact = (identity is not None and identity.get("single_ingredient") is True
                         and set(identity["ingredient_rxcuis"]) == {selector["ingredient_rxcui"]}
                         and ("allowed_product_rxcuis" not in selector
                              or drug.get("code") in selector["allowed_product_rxcuis"]))
            else:
                exact = drug.get("system") == selector["system"] and drug.get("code") == selector["code"]
            broad = drug.get("system") == "ATC3" and drug.get("code") in rule.get("possible_atc3", [])
            if not (exact or broad):
                continue
            matched = True
            fields = []
            if broad:
                fields = [f"candidates[{index}].drug.exact_ingredient_identity"]
            elif product_rule:
                mismatch = []
                if identity.get("route") is not None and identity["route"] != selector["route"]:
                    mismatch.append("route")
                if identity.get("dose_form_rxcui") is not None and identity["dose_form_rxcui"] not in selector["allowed_dose_form_rxcuis"]:
                    mismatch.append("dose_form_rxcui")
                if mismatch:
                    reasons.append({"code": "outside_label_scope", "candidate_index": index,
                                    "rule_id": rule["rule_id"], "fields": mismatch})
                    continue
                fields = [f"candidates[{index}].drug.identity.{name}" for name in ("route", "dose_form_rxcui")
                          if identity.get(name) is None]
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
                finding = {"rule_id": rule["rule_id"], "version": rule["version"],
                    "candidate_index": index, "drug": dict(drug), "action": "flag", "statement": rule["statement"],
                    "known_facts": {key: context[key] for key in rule["required_fields"] if context.get(key) is not None},
                    "source": rule["source"], "evidence": rule["evidence"]}
                if product_rule:
                    finding.update(identity=dict(identity), identity_sources=product["sources"],
                                   scope_review=rule.get("scope_review"), scope_evidence=rule.get("scope_evidence", []))
                if "classification" in rule:
                    finding["classification"] = rule["classification"]
                report["findings"].append(finding)
        if not matched:
            reasons.append({"code": "candidate_not_covered", "candidate_index": index, "drug": dict(drug)})
    report["coverage"]["checked_candidate_count"] = len(checked_candidates)
    if pair_rules:
        _check_candidate_pairs(candidates, pair_rules, products, known_source_codes, report)
    if report["findings"]:
        report["status"] = "issues_found"
    elif report["coverage"]["pending_rule_count"] or report.get("pair_coverage", {}).get("pending_pair_count"):
        report["status"] = "insufficient_information"
    elif report["coverage"]["checked_rule_count"]:
        report["status"] = "checked"
    return report
