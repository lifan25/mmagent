"""Freeze a positive-list DDI pilot, then score pair localization without label leakage.

Responses are JSONL envelopes: {"case_id": "ddi-list-0001", "response":
{"target_pair": [1, 2]}}. The response may instead contain raw model JSON text.
Only {"target_pair": [presented_slot, presented_slot]} or {"target_pair": "unknown"}
is accepted. This benchmark has no negative lists and cannot estimate their FPR.
"""

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261114
PREPARED = ROOT / "data/processed/knowledge/ddi-lists-20261114"
PERMUTED = ROOT / "data/processed/knowledge/ddi-lists-permuted-20261114"
FIELDS = [f"Drug {slot}" for slot in range(1, 7)] + [
    "Total number of drugs", "Full Drug list with doses", "DDI", "Classification"]


def normalized_name(value):
    # No fuzzy matching, spelling correction, salt/route removal, or post-result aliases.
    return " ".join(value.casefold().split())


def reference_pair(row):
    names = re.split(r"\s+and\s+", row["DDI"].strip(), flags=re.IGNORECASE)
    if len(names) != 2:
        return None, ["label_does_not_contain_exactly_two_and_separated_names"]
    matches = [[slot for slot in range(1, 7) if normalized_name(row[f"Drug {slot}"]) == normalized_name(name)]
               for name in names]
    issues = []
    for name, slots in zip(names, matches):
        if len(slots) != 1:
            issues.append({"label_name": name, "matched_slots": slots,
                           "reason": "unmapped_name" if not slots else "ambiguous_name"})
    if issues:
        return None, issues
    pair = sorted(slots[0] for slots in matches)
    return (None, ["both_names_map_to_same_slot"]) if pair[0] == pair[1] else (pair, [])


def freeze_split(count):
    if count != 250:
        raise ValueError("Expected the fixed 250-list source; do not silently change this pilot")
    selected = random.Random(SEED).sample(range(count), 55)
    return {"pilot": sorted(selected[:50]), "development": sorted(selected[50:]),
            "sealed": sorted(set(range(count))-set(selected))}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows), encoding="utf-8")


def read_jsonl(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_empty(output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is nonempty; preserve the frozen split and previous results")
    output.mkdir(parents=True, exist_ok=True)


def case_records(row, source_row, permuted=False):
    case_id = f"ddi-list-{source_row:04d}"
    presented = {"case_id": case_id, **{f"drug{slot}": row[f"Drug {slot}"] for slot in range(1, 7)},
                 "doses": row["Full Drug list with doses"]}
    slot_map = {slot: slot for slot in range(1, 7) if row[f"Drug {slot}"].strip()}
    if permuted:
        drugs = [(slot, row[f"Drug {slot}"]) for slot in range(1, 7) if row[f"Drug {slot}"].strip()]
        random.Random(SEED + source_row).shuffle(drugs)
        presented.update({f"drug{slot}": drugs[slot-1][1] if slot <= len(drugs) else "" for slot in range(1, 7)})
        presented["doses"] = ""
        slot_map = {original: new for new, (original, _) in enumerate(drugs, 1)}
    # Label reading occurs after presentation; permutation never depends on the reference pair.
    original_pair, issues = reference_pair(row)
    pair = sorted(slot_map[slot] for slot in original_pair) if original_pair is not None else None
    label = {"case_id": case_id, "source_row": source_row, "ddi_text": row["DDI"],
             "classification": row["Classification"], "target_pair": pair, "mapping_issues": issues}
    if permuted:
        label.update(original_target_pair=original_pair, original_to_presented_slots=slot_map,
                     mapping_issues_slot_space="original")
    return presented, label


def prepare(source, output, permuted=False):
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"Unexpected source columns: {reader.fieldnames}")
        rows = list(reader)
    split = freeze_split(len(rows))
    ensure_empty(output)
    summaries = {}
    for name in ("development", "pilot"):
        inputs, labels = [], []
        for index in split[name]:
            case_input, label = case_records(rows[index], index+1, permuted)
            inputs.append(case_input)
            labels.append(label)
        write_jsonl(output / f"{name}.inputs.jsonl", inputs)
        write_jsonl(output / f"{name}.labels.jsonl", labels)
        summaries[name] = {"lists": len(inputs), "mappable_references": sum(row["target_pair"] is not None for row in labels),
                           "mapping_issue_lists": sum(bool(row["mapping_issues"]) for row in labels)}
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "source": str(source.resolve()),
        "source_sha256": digest(source), "script_sha256": digest(Path(__file__)), "seed": SEED,
        "selection": "random.Random(seed).sample(range(250),55); first 50 pilot, next 5 development; output sorted by original row",
        "split_ids": {name: [f"ddi-list-{i+1:04d}" for i in indices] for name, indices in split.items()},
        "summaries": summaries, "sealed_lists": len(split["sealed"]),
        "frozen_files": {path.name: digest(path) for path in sorted(output.glob("*.jsonl"))},
        "mapping_policy": "Casefold and whitespace normalization only; no manual aliases or inferred drug substitutions.",
        "model_input_fields": [f"drug{i}" for i in range(1, 7)] + ["doses"],
        "case_id_role": "Outer bookkeeping identifier; not part of clinical model input.",
        "response_schema": {"case_id": "outer identifier", "response": {"target_pair": "two distinct nonempty presented slot numbers or literal unknown"}},
        "presentation": ({"variant": "v2_permuted_drug_names_only", "per_case_seed": "20261114 + one-based source data row",
                          "permutation": "Shuffle nonempty original slots once with random.Random; fill presented slots 1..k.",
                          "doses": "Omitted (empty string): original free text exposes drug order and is not safely reorderable.",
                          "label_mapping": "Original-to-presented slot map is evaluator-only in labels.jsonl.",
                          "scope": "Protocol correction before any LLM inference; differs from the original dose-containing benchmark."}
                         if permuted else {"variant": "v1_original_order", "doses": "Original text retained."}),
        "evaluation_rules": ["Development is for format checks only; freeze prompt before first pilot inference.",
                             "Do not tune prompts, select models, or add aliases using pilot answers.",
                             "The remaining 195 lists are sealed and are not materialized as model input here.",
                             "DDI and Classification are evaluator-only labels, never model input.",
                             "All lists carry a reference interaction; no list-level false-positive rate can be estimated."]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_response(response, case_input):
    try:
        result = json.loads(response) if isinstance(response, str) else response
    except (ValueError, TypeError):
        return "invalid", None, "response_is_not_json"
    if not isinstance(result, dict) or set(result) != {"target_pair"}:
        return "invalid", None, "expected_only_target_pair_key"
    pair = result["target_pair"]
    if pair == "unknown":
        return "unknown", None, None
    if not isinstance(pair, list) or len(pair) != 2 or any(type(slot) is not int for slot in pair):
        return "invalid", None, "expected_two_integer_slots_or_unknown"
    if pair[0] == pair[1] or any(slot not in range(1, 7) for slot in pair):
        return "invalid", None, "slots_must_be_distinct_and_between_1_and_6"
    if any(not case_input[f"drug{slot}"].strip() for slot in pair):
        return "invalid", None, "selected_empty_drug_slot"
    return "answered", sorted(pair), None


def score(inputs, labels, responses):
    cases = {row["case_id"]: row for row in inputs}
    references = {row["case_id"]: row for row in labels}
    if len(cases) != len(inputs) or len(references) != len(labels) or cases.keys() != references.keys():
        raise ValueError("Duplicate or mismatched input/reference identifiers")
    predictions = {}
    for envelope in responses:
        if not isinstance(envelope, dict) or "case_id" not in envelope or "response" not in envelope:
            raise ValueError("Responses must preserve case_id and raw response in an outer JSONL envelope")
        key = envelope["case_id"]
        if key not in cases or key in predictions:
            raise ValueError("Unexpected or duplicate response identifier; do not select among repeated attempts")
        predictions[key] = envelope["response"]
    counts = Counter(total_lists=len(cases))
    invalid_reasons = Counter()
    mapping_issues = []
    for key, case_input in cases.items():
        reference = references[key]["target_pair"]
        if reference is None:
            counts["mapping_issue_lists"] += 1
            mapping_issues.append({"case_id": key, "issues": references[key]["mapping_issues"]})
        else:
            counts["scorable_lists"] += 1
        if key not in predictions:
            status, pair, reason = "missing", None, None
        else:
            status, pair, reason = parse_response(predictions[key], case_input)
        counts[status] += 1
        if reason:
            invalid_reasons[reason] += 1
        if status == "answered" and reference is not None:
            counts["scorable_answered"] += 1
            counts["exact_matches"] += pair == sorted(reference)
        elif status == "answered":
            counts["answered_with_unmappable_reference"] += 1
    for key in ("answered", "unknown", "missing", "invalid", "mapping_issue_lists", "scorable_lists",
                "scorable_answered", "exact_matches", "answered_with_unmappable_reference"):
        counts.setdefault(key, 0)
    def ratio(numerator, denominator):
        return {"numerator": counts[numerator], "denominator": counts[denominator],
                "value": counts[numerator]/counts[denominator] if counts[denominator] else None}
    return {"counts": dict(counts), "metrics": {
        "interaction_localization_exact_match": ratio("exact_matches", "scorable_lists"),
        "answer_coverage": ratio("answered", "total_lists"),
        "answered_precision_on_mappable_references": ratio("exact_matches", "scorable_answered"),
        "confirmed_exact_matches_over_all_lists": ratio("exact_matches", "total_lists"),
        "invalid_response_rate": ratio("invalid", "total_lists")},
        "invalid_reasons": dict(invalid_reasons), "mapping_issues": mapping_issues,
        "limitations": ["Only the designated reference pair is scored; another predicted pair is not thereby proven clinically false.",
                        "Unknown, missing and invalid answers do not count as exact matches on mappable cases.",
                        "Unmappable references remain in coverage and total-list counts; their correctness is not scored.",
                        "Positive-list localization only: no negative-list false-positive rate, clinical safety, or efficacy estimate."]}


def evaluate(prepared, responses, split, output, run_info=None):
    manifest = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
    paths = [prepared / f"{split}.{part}.jsonl" for part in ("inputs", "labels")]
    for path in paths:
        if digest(path) != manifest["frozen_files"][path.name]:
            raise ValueError("Frozen input/reference file changed after preparation")
    inputs, labels = [read_jsonl(path) for path in paths]
    if [row["case_id"] for row in inputs] != manifest["split_ids"][split]:
        raise ValueError("Input identifiers differ from the frozen split")
    report = score(inputs, labels, read_jsonl(responses))
    report["provenance"] = {"created_utc": datetime.now(timezone.utc).isoformat(), "split": split,
                            "prepared": str(prepared.resolve()), "manifest_sha256": digest(prepared / "manifest.json"),
                            "responses": str(responses.resolve()), "responses_sha256": digest(responses),
                            "script_sha256": digest(Path(__file__))}
    if run_info is not None:
        report["run_info"] = json.loads(run_info.read_text(encoding="utf-8"))
    ensure_empty(output)
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def first_two(prepared, split, output):
    inputs = read_jsonl(prepared / f"{split}.inputs.jsonl")
    responses = []
    for row in inputs:
        slots = [slot for slot in range(1, 7) if row[f"drug{slot}"].strip()]
        responses.append({"case_id": row["case_id"], "response": {"target_pair": slots[:2] if len(slots) >= 2 else "unknown"}})
    ensure_empty(output)
    write_jsonl(output / "responses.jsonl", responses)
    run_info = output / "run-info.json"
    run_info.write_text(json.dumps({"execution": "deterministic_baseline", "rule": "First two nonempty presented slots; inputs only; no model."}), encoding="utf-8")
    return evaluate(prepared, output / "responses.jsonl", split, output / "evaluation", run_info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare")
    prep.add_argument("--source", type=Path, default=ROOT / "data/local/llm-uncertainty-ddi/drug5.csv")
    prep.add_argument("--output", type=Path, default=PREPARED)
    permuted = subparsers.add_parser("prepare-permuted")
    permuted.add_argument("--source", type=Path, default=ROOT / "data/local/llm-uncertainty-ddi/drug5.csv")
    permuted.add_argument("--output", type=Path, default=PERMUTED)
    baseline = subparsers.add_parser("first-two")
    baseline.add_argument("--prepared", type=Path, default=PERMUTED)
    baseline.add_argument("--split", choices=("development", "pilot"), default="pilot")
    baseline.add_argument("--output", type=Path, required=True)
    evaluation = subparsers.add_parser("evaluate")
    evaluation.add_argument("--prepared", type=Path, default=PREPARED)
    evaluation.add_argument("--responses", type=Path, required=True)
    evaluation.add_argument("--split", choices=("development", "pilot"), default="pilot")
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--run-info", type=Path)
    args = parser.parse_args()
    if args.command in ("prepare", "prepare-permuted"):
        result = prepare(args.source, args.output, permuted=args.command == "prepare-permuted")
        print(json.dumps({"prepared": str(args.output), "summaries": result["summaries"], "sealed_lists": result["sealed_lists"]}, indent=2))
    else:
        result = (first_two(args.prepared, args.split, args.output) if args.command == "first-two" else
                  evaluate(args.prepared, args.responses, args.split, args.output, args.run_info))
        print(json.dumps({"output": str(args.output), "counts": result["counts"], "metrics": result["metrics"]}, indent=2))
