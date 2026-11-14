"""Check the frozen predictor against saved scores, without training or selection."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from .predict import ROOT, SSPNetRecommender
from .prepare import read_jsonl
from .train import evaluate


def run(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output already exists; use another verification directory")
    start = time.perf_counter()
    predictor = SSPNetRecommender()
    loaded_seconds = time.perf_counter() - start
    prepared = predictor.prepared_dir
    rows = read_jsonl(prepared / "test.jsonl")
    run_dir = predictor.checkpoint_path.parent
    previous = np.load(run_dir / "test-scores.npy", allow_pickle=False)
    old_predictions = read_jsonl(run_dir / "test-predictions.jsonl")
    if [r["case_id"] for r in rows] != [r["case_id"] for r in old_predictions]:
        raise ValueError("Saved prediction order differs from the fixed encoded test set")
    with np.load(prepared / "graphs.npz", allow_pickle=False) as graphs:
        metrics, scores = evaluate(predictor.model, rows, len(predictor.medication_codes),
                                   graphs["ddi"], predictor.threshold, graphs["ddi_mapping_mask"])
    if scores.shape != previous.shape or not np.array_equal(scores, previous):
        difference = float(np.max(np.abs(scores - previous))) if scores.shape == previous.shape else None
        raise AssertionError(f"Encoded-score equality failed: max_abs_difference={difference}")
    examples = read_jsonl(ROOT / predictor.config["a1_dir"] / "main_prediction_examples.jsonl")
    source = {r["case"]["case_id"]: r for r in examples}
    if len(source) != len(examples):
        raise ValueError("A1 case identifiers are not unique")
    statuses, issue_codes = Counter(), Counter()
    alignment, accepted_indices = [], []
    for index, row in enumerate(rows):
        original = source[row["case_id"]]
        if original["split"] != "test":
            raise ValueError("A1 split differs from the saved test set")
        encoded, status, issues = predictor._encode_case(original["case"])
        statuses[status] += 1
        issue_codes.update(i["code"] for i in issues)
        if status == "ok":
            if encoded != row["input"]:
                raise AssertionError("Strict Case encoding differs from the frozen prepared row")
            accepted_indices.append(index)
        alignment.append({"case_id": row["case_id"], "status": status, "input_issues": issues,
                          "encoded_input": encoded, "prepared_input": row["input"]})
    if not accepted_indices:
        raise AssertionError("No raw A1 Case supported by the public interface")
    index = accepted_indices[0]
    case = source[rows[index]["case_id"]]["case"]
    inference_start = time.perf_counter()
    handoff = predictor.score_case(case)
    inference_seconds = time.perf_counter() - inference_start
    if handoff["recommendation"]["status"] != "ok" or not np.array_equal(handoff["full_scores"], previous[index]):
        raise AssertionError("Public score_case does not match the saved encoded prediction")
    output.mkdir(parents=True, exist_ok=True)
    np.save(output / "encoded-test-scores.npy", scores)
    with (output / "case-encoding-alignment.jsonl").open("w", encoding="utf-8") as handle:
        for row in alignment:
            handle.write(json.dumps(row) + "\n")
    (output / "a1-case-handoff.json").write_text(json.dumps({"case": case, **handoff,
        "evaluation_only_target_ids": rows[index]["target"]}, indent=2), encoding="utf-8")
    (output / "model-manifest.json").write_text(json.dumps(predictor.manifest, indent=2), encoding="utf-8")
    report = {
        "scope": "Frozen inference compatibility; no training, tuning or new efficacy claim",
        "model_version": predictor.model_version,
        "encoded_test_samples": len(rows), "medication_classes": len(predictor.medication_codes),
        "all_encoded_scores_bitwise_equal": True, "max_score_absolute_difference": 0.0,
        "threshold": predictor.threshold,
        "all_encoded_candidate_sets_equal": bool(np.array_equal(scores >= predictor.threshold, previous >= predictor.threshold)),
        "strict_raw_case_status_counts": dict(statuses), "strict_issue_occurrences": dict(issue_codes),
        "strict_supported_encoding_equal": len(accepted_indices),
        "public_score_case_checked_samples": 1, "public_score_case_scores_equal": True,
        "public_score_case_current_medications_empty": handoff["encoded_input"][-1][2] == [],
        "strict_supported_empty_current_procedures": sum(rows[i]["empty_current_procedures"] for i in accepted_indices),
        "existing_encoded_test_metrics": metrics["overall"],
        "constructor_seconds_excluding_import": loaded_seconds,
        "one_public_inference_seconds": inference_seconds,
        "verification_seconds_excluding_import": time.perf_counter() - start,
        "artifact_sha256": predictor.manifest["sha256"],
        "limitations": ["The encoded 351-case path retains the historical preprocessing UNK/drop policy; it is not the strict public Case interface.",
                        "Raw Cases with unsupported codes are rejected without inference; do not silently compare only the accepted subset with the original full test score.",
                        "One public score_case was inferred here; all supported raw Cases were encoding-aligned. A performs the separate full integrated run.",
                        "The historical Synthea test set is exploratory; no clinical validation or zero-shot inference was performed."]}
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/recommendation/predict-verification-20261114")
    run(parser.parse_args().output)
