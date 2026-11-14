"""Evaluate the integrated agent without retraining or changing the fixed cohort."""

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

import numpy as np

from src.data_evaluation.pipeline import DEFAULT_AGENT_RULES, MedicationAgent, ROOT
from src.recommendation.prepare import read_jsonl
from src.recommendation.train import metrics


def run(split, output, rules_path=None, config_path=None, context_path=None, products_path=None):
    if output.exists():
        raise ValueError("Run directory exists; preserve the existing evidence")
    config_path = config_path or ROOT / "src/recommendation/configs/sspnet-synthea-product.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    a1 = ROOT / config["a1_dir"]
    prepared = ROOT / config["prepared_dir"]
    all_examples = [r for r in read_jsonl(a1 / "main_prediction_examples.jsonl") if r["split"] == split]
    encoded = read_jsonl(prepared / f"{split}.jsonl")
    size = len(json.loads((prepared / "vocabulary.json").read_text())["medications"])
    positions = {r["case_id"]: i for i, r in enumerate(encoded)}
    graph = np.load(prepared / "graphs.npz")
    from src.knowledge.check import load_rules
    rules_path = rules_path or DEFAULT_AGENT_RULES
    rules = load_rules(rules_path)
    from src.recommendation.predict import SSPNetRecommender
    products = json.loads(products_path.read_text(encoding="utf-8")) if products_path else None
    agent = MedicationAgent(recommender=SSPNetRecommender(ROOT / config["run_dir"] / "best.pt"), rules=rules,
                            product_metadata=products)
    context = json.loads(context_path.read_text(encoding="utf-8")) if context_path else None
    original_scores = np.load(ROOT / config["run_dir"] / "test-scores.npy") if split == "test" else None
    if original_scores is not None and len(original_scores) != len(encoded):
        raise ValueError("Original score rows no longer match the fixed test cohort")
    output.mkdir(parents=True)
    supported_rows, supported_scores, baseline_scores, encoded_equal = [], [], [], []
    statuses, recommendation_statuses, checks, input_issues, missing = (Counter() for _ in range(5))
    patient_ids, supported_patient_ids = set(), set()
    checked_rules = pending_rules = unsupported_targets = 0
    start = time.perf_counter()
    with (output / "agent-results.jsonl").open("x", encoding="utf-8") as stream:
        for number, row in enumerate(all_examples, 1):
            patient_ids.add(row["patient_id"])
            case = row["case"]
            if context is not None:
                from src.data_evaluation.prepare_context import apply_context
                case = apply_context(case, context)
            report, scored = agent.run_with_scores(case)
            rec, checked = report["recommendation"], report["check_report"]
            statuses[report["status"]] += 1
            recommendation_statuses[rec["status"]] += 1
            input_issues.update(issue["code"] for issue in rec["input_issues"])
            if checked is not None:
                checks[checked["status"]] += 1
                for item in checked["missing_fields"]:
                    fields = [item] if isinstance(item, str) else item.get("fields", [item.get("field", "unspecified")])
                    missing.update(fields)
                checked_rules += checked["coverage"].get("checked_rule_count", 0)
                pending_rules += checked["coverage"].get("pending_rule_count", 0)
            if rec["status"] == "ok":
                index = positions.get(row["case"]["case_id"])
                if index is None:
                    unsupported_targets += 1
                else:
                    expected = encoded[index]
                    encoded_equal.append(scored["encoded_input"] == expected["input"])
                    if not encoded_equal[-1]:
                        raise ValueError("Public adapter and fixed preparation produced different model inputs")
                    supported_rows.append(expected)
                    supported_scores.append(scored["full_scores"])
                    supported_patient_ids.add(row["patient_id"])
                    if original_scores is not None:
                        baseline_scores.append(original_scores[index])
            # Targets remain in the evaluator's source records; the tool trace contains none.
            stream.write(json.dumps({"patient_id": row["patient_id"], "agent": report,
                                     "full_scores": scored["full_scores"]}, ensure_ascii=False, allow_nan=False)+"\n")
            if number % 100 == 0 or number == len(all_examples):
                print(json.dumps({"processed": number, "total": len(all_examples)}), flush=True)
    probabilities = np.asarray(supported_scores, dtype=np.float32)
    args = (size, graph["ddi"], config["threshold"], graph["ddi_mapping_mask"])
    supported_metrics = metrics(supported_rows, probabilities, *args)
    total, valid = len(all_examples), len(supported_rows)
    report = {
        "task": "Existing SSPNet checkpoint with public Case interface and sourced rule-check agent",
        "contract_version": "0.1-draft", "split": split,
        "repository_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "a1_directory": config["a1_dir"], "prepared_directory": config["prepared_dir"],
        "checkpoint_directory": config["run_dir"], "model_manifest": agent.recommender.manifest,
        "context_file": str(context_path) if context_path else None,
        "product_metadata_file": str(products_path) if products_path else None,
        "context_policy": context["policy"] if context else "original A1 context only",
        "rules_file": str(Path(rules_path).resolve().relative_to(ROOT)),
        "rule_versions": [{"rule_id": r["rule_id"], "version": r["version"],
                           "review_status": r["review_status"]} for r in rules],
        "training_performed": False, "threshold_changed": False, "candidate_modification": False,
        "input_cases": total, "input_patients": len(patient_ids), "prepared_evaluable_cases": len(encoded),
        "supported_evaluable_cases": valid, "supported_patients": len(supported_patient_ids),
        "recommendation_coverage": recommendation_statuses["ok"]/total,
        "supported_predictions_without_evaluable_target": unsupported_targets,
        "recommendation_statuses": dict(recommendation_statuses), "agent_statuses": dict(statuses),
        "knowledge_statuses": dict(checks), "input_issue_counts": dict(input_issues),
        "missing_field_occurrences": dict(missing), "checked_rule_instances": checked_rules,
        "pending_rule_instances": pending_rules, "supported_metrics": supported_metrics,
        "all_input_cases_with_nonanswers_scored_zero": {
            "denominator": total,
            "jaccard": supported_metrics.get("jaccard", 0)*valid/total,
            "f1": supported_metrics.get("f1", 0)*valid/total,
            "scope": "Unsupported inputs remain in denominator; AP is not defined for nonanswers and is not filled with invented scores."},
        "encoded_inputs_equal_on_supported": all(encoded_equal), "seconds": time.perf_counter()-start,
        "limitations": [
            "Exploratory Synthea adaptation, not independent clinical validation or a new training result.",
            "Strict public inputs may be rejected where legacy preprocessing used UNK or dropped medications; coverage and supported metrics are separate.",
            "ATC3 cannot identify an ingredient; RxNorm identity requires a separate frozen product source. Missing prerequisites remain unresolved.",
            "Flag-only checks do not improve medication prediction metrics; no independent clinical adjudication labels are available.",
            "DXY diagnosis is a separate evaluation, never joined to these patients."]}
    if original_scores is not None:
        baseline = np.asarray(baseline_scores, dtype=np.float32)
        report["stored_scores_comparison"] = {
            "max_absolute_difference": float(np.max(np.abs(probabilities-baseline))) if valid else None,
            "allclose_atol_1e_7_rtol_0": bool(np.allclose(probabilities, baseline, atol=1e-7, rtol=0)) if valid else None,
            "original_same_supported_cases": metrics(supported_rows, baseline, *args)}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "input_cases": total, "supported_cases": valid,
                      "knowledge_statuses": dict(checks), "seconds": report["seconds"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/data_evaluation/agent-integration-20261114")
    parser.add_argument("--rules", type=Path, help="Reviewed package for a fixed-candidate comparison")
    parser.add_argument("--config", type=Path, help="Existing training config and checkpoint; no retraining here")
    parser.add_argument("--context", type=Path, help="Frozen optional same-encounter context")
    parser.add_argument("--products", type=Path, help="Frozen product identity snapshot for selected rules")
    args = parser.parse_args()
    run(args.split, args.output, args.rules, args.config, args.context, args.products)
