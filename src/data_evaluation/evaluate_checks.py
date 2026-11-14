"""Evaluate frozen source references and replay checks on unchanged recommendations."""

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

from src.knowledge.check import check, load_product_metadata, load_rules
from src.recommendation.prepare import read_jsonl
from .pipeline import ROOT
from .prepare_context import apply_context

STATES = ("flag", "clear_within_rule", "unknown", "not_applicable")


def reference_state(report):
    """Classify only the requested rule family, never whole-prescription safety."""
    if report["findings"]:
        return "flag"
    pair = report.get("pair_coverage", {})
    if report["coverage"]["pending_rule_count"] or pair.get("pending_pair_count", 0) or report["missing_fields"]:
        return "unknown"
    if report["coverage"]["checked_rule_count"] or pair.get("checked_pair_count", 0):
        return "clear_within_rule"
    return "not_applicable"


def summarize_reference(rows):
    matrix = {expected: {predicted: 0 for predicted in STATES} for expected in STATES}
    families = defaultdict(lambda: Counter(total=0, agreements=0))
    for row in rows:
        matrix[row["expected"]][row["actual"]] += 1
        families[row["family"]].update(total=1, agreements=row["expected"] == row["actual"])
    total = len(rows)
    return {"reference_cases": total, "agreements": sum(matrix[s][s] for s in STATES),
            "agreement_rate": sum(matrix[s][s] for s in STATES) / total if total else None,
            "confusion_matrix_expected_rows": matrix,
            "by_family": {family: {**count, "agreement_rate": count["agreements"]/count["total"]}
                          for family, count in families.items()},
            "by_expected_state": {s: {"total": sum(matrix[s].values()), "agreements": matrix[s][s],
                "agreement_rate": matrix[s][s]/sum(matrix[s].values()) if sum(matrix[s].values()) else None}
                for s in STATES},
            "unknown_misreported_clear": matrix["unknown"]["clear_within_rule"],
            "missed_reference_flags": sum(matrix["flag"].values()) - matrix["flag"]["flag"],
            "false_flags_against_reference": sum(matrix[s]["flag"] for s in STATES if s != "flag")}


def evaluate_reference(reference_path, rules, products):
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    available = {r["rule_id"]: r for r in rules}
    rows = []
    for item in reference["cases"]:
        if item["expected"] not in STATES or not item["rule_ids"]:
            raise ValueError("Invalid frozen reference")
        selected = [available[rule_id] for rule_id in item["rule_ids"]]
        case = {"contract_version": "0.1-draft", "data_kind": "synthetic", "case_id": item["reference_id"],
                "context": item["context"]}
        rec = {**{key: case[key] for key in ("contract_version", "data_kind", "case_id")},
               "status": "ok", "execution": "synthetic_fixture", "model_version": "source-reference-no-model",
               "candidates": [{"drug": drug, "score": 1.0} for drug in item["candidates"]]}
        original = copy.deepcopy(rec)
        report = check(case, rec, selected, product_metadata=products)
        if rec != original:
            raise ValueError("Rule checker mutated a reference candidate")
        rows.append({"reference_id": item["reference_id"], "family": item["family"],
                     "expected": item["expected"], "actual": reference_state(report), "report": report})
    summary = summarize_reference(rows)
    summary.update(reference_version=reference["version"],
                   reference_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                   reference_scope="Independently authored source-reference conformance, not expert clinical ground truth")
    return rows, summary


def replay(cases, saved, snapshot, rules, products):
    statuses, coverage, pairs, single_rules, pair_rules = (Counter() for _ in range(5))
    supported = any_single = any_pair = any_check = flagged_cases = pair_universe = 0
    executed_rule_cases = Counter()
    rows = []
    for cid, source in cases.items():
        rec = saved[cid]["agent"]["recommendation"]
        if rec["status"] != "ok":
            rows.append({"case_id": cid, "recommendation_status": rec["status"], "check_report": None})
            continue
        supported += 1
        pair_universe += len(rec["candidates"]) * (len(rec["candidates"])-1) // 2
        context_case = apply_context(source, snapshot)
        original = copy.deepcopy(rec)
        report = check(context_case, rec, rules, product_metadata=products)
        if rec != original:
            raise ValueError("Check replay changed the frozen recommendation")
        statuses[report["status"]] += 1
        c, p = report["coverage"], report.get("pair_coverage", {})
        coverage.update({k: c.get(k, 0) for k in ("checked_rule_count", "pending_rule_count", "checked_candidate_count", "candidate_count")})
        pairs.update({k: p.get(k, 0) for k in ("candidate_pair_count", "checked_pair_count", "pending_pair_count", "uncovered_pair_count")})
        single, pair = c["checked_rule_count"] > 0, p.get("checked_pair_count", 0) > 0
        any_single += single
        any_pair += pair
        any_check += single or pair
        flagged_cases += bool(report["findings"])
        executed_rule_cases.update(r["rule_id"] for r in report["applied_rules"])
        for finding in report["findings"]:
            (pair_rules if "candidate_indices" in finding else single_rules)[finding["rule_id"]] += 1
        rows.append({"case_id": cid, "recommendation_status": "ok", "check_report": report})
    summary = {"input_cases": len(cases), "supported_cases": supported, "rejected_inputs": len(cases)-supported,
               "statuses": dict(statuses), "single_rule_coverage": dict(coverage), "pair_coverage": dict(pairs),
               "candidate_pair_universe": pair_universe, "executed_rule_case_counts": dict(executed_rule_cases),
               "cases_with_single_rule_executed": any_single, "cases_with_pair_rule_executed": any_pair,
               "cases_with_any_check_executed": any_check,
               "any_check_case_coverage_supported": any_check/supported if supported else None,
               "any_check_case_coverage_all_inputs": any_check/len(cases) if cases else None,
               "flagged_cases": flagged_cases, "single_rule_flags": dict(single_rules), "potential_pair_flags": dict(pair_rules),
               "candidates_unchanged": True, "clinical_accuracy": None}
    return rows, summary


def run(args):
    if args.output.exists():
        raise ValueError("Preserve existing evaluation; choose a new output directory")
    rules = {"old": load_rules(args.old_rules), "new": load_rules(args.new_rules)}
    products = {"old": load_product_metadata(args.old_products), "new": load_product_metadata(args.new_products)}
    contexts = {"old": json.loads(args.old_context.read_text(encoding="utf-8")),
                "new": json.loads(args.new_context.read_text(encoding="utf-8"))}
    examples = [r for r in read_jsonl(args.a1_dir / "main_prediction_examples.jsonl") if r["split"] == "test"]
    cases = {r["case"]["case_id"]: r["case"] for r in examples}
    saved = {r["agent"]["case_id"]: r for r in read_jsonl(args.saved_run / "agent-results.jsonl")}
    if set(cases) != set(saved):
        raise ValueError("Saved prediction and raw input cohorts differ")
    ref_rows, ref_summary = evaluate_reference(args.reference, rules["new"], products["new"])
    outputs, summaries = {}, {}
    for rule_version, context_version in product(("old", "new"), repeat=2):
        name = f"{rule_version}_rules_{context_version}_facts"
        outputs[name], summaries[name] = replay(cases, saved, contexts[context_version], rules[rule_version], products[rule_version])
    baseline_equal = all(row["check_report"] == saved[row["case_id"]]["agent"]["check_report"]
                         for row in outputs["old_rules_old_facts"])
    if not baseline_equal:
        raise ValueError("Old rules/old facts replay no longer reproduces saved baseline")
    result = {"scope": "Fixed-prediction retrospective rule evaluation; no model inference or training",
              "reference": ref_summary, "arms": summaries, "baseline_check_reports_equal": baseline_equal,
              "prediction_source": str(args.saved_run), "reference_path": str(args.reference),
              "rule_paths": {"old": str(args.old_rules), "new": str(args.new_rules)},
              "product_paths": {"old": str(args.old_products), "new": str(args.new_products)},
              "context_paths": {"old": str(args.old_context), "new": str(args.new_context)},
              "limitations": ["No independently adjudicated clinical labels for these patient records.",
                              "Source references are synthetic and role-separated, not statistically independent model or expert annotations.",
                              "New scope includes product-source narrowing, additional single-drug rules and potential candidate combinations.",
                              "A checked rule or proposed pair never means a whole prescription is safe or drugs were actually coadministered."]}
    args.output.mkdir(parents=True)
    for name, rows in {"reference-evaluations": ref_rows, **outputs}.items():
        with (args.output / (name + ".jsonl")).open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"reference": ref_summary, "arms": summaries, "baseline_equal": baseline_equal}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--a1-dir", type=Path, default=ROOT / "data/processed/data_evaluation/synthea-apr2020-v3")
    p.add_argument("--saved-run", type=Path, default=ROOT / "outputs/data_evaluation/agent-rxnorm-context-20261114")
    p.add_argument("--old-context", type=Path, default=ROOT / "data/processed/data_evaluation/synthea-context-v1/context.json")
    p.add_argument("--new-context", type=Path, default=ROOT / "data/processed/data_evaluation/synthea-context-v2/context.json")
    p.add_argument("--old-rules", type=Path, default=ROOT / "src/knowledge/rules/medication-llm-rxnorm-scope-v1.json")
    p.add_argument("--new-rules", type=Path, default=ROOT / "src/knowledge/rules/medication-source-reviewed-v2.json")
    p.add_argument("--old-products", type=Path, default=ROOT / "src/knowledge/rules/rxnorm-rule-products-v1.json")
    p.add_argument("--new-products", type=Path, default=ROOT / "src/knowledge/rules/rxnorm-rule-products-v2.json")
    p.add_argument("--reference", type=Path, default=ROOT / "src/data_evaluation/resources/check-reference-v1.json")
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
