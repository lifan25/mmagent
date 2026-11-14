"""Frozen exact-name DDInter retrieval baseline, independent of reference labels."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from .evaluate_ddi_lists import (
    PERMUTED, ROOT, digest, ensure_empty, evaluate, normalized_name, read_jsonl, write_jsonl,
)

FILES = [f"ddinter_downloads_code_{code}.csv" for code in "ABDHLPRV"]
FIELDS = ["DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"]
RANK = {"major": 3, "moderate": 2, "minor": 1}


def build_index(paths):
    names, pairs = defaultdict(set), {}
    row_count = 0
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != FIELDS:
                raise ValueError(f"Unexpected DDInter columns: {path.name}")
            for row in reader:
                row_count += 1
                for suffix in ("A", "B"):
                    names[normalized_name(row[f"Drug_{suffix}"])].add(row[f"DDInterID_{suffix}"])
                key = tuple(sorted((row["DDInterID_A"], row["DDInterID_B"])))
                item = pairs.setdefault(key, {"levels": set(), "source_files": set(), "source_row_count": 0})
                item["levels"].add(row["Level"])
                item["source_files"].add(path.name)
                item["source_row_count"] += 1
    conflicts = [{"ddinter_ids": list(key), "levels": sorted(item["levels"]),
                  "source_files": sorted(item["source_files"])} for key, item in pairs.items()
                 if len({normalized_name(level) for level in item["levels"]}) > 1]
    summary = {"csv_files": len(paths), "source_rows": row_count, "unique_unordered_id_pairs": len(pairs),
               "duplicate_pair_rows": row_count-len(pairs), "normalized_names": len(names),
               "ambiguous_normalized_names": sum(len(ids) > 1 for ids in names.values()),
               "level_conflict_pairs": len(conflicts)}
    return names, pairs, summary, conflicts


def retrieve(case, names, index):
    drugs = []
    for slot in range(1, 7):
        name = case[f"drug{slot}"]
        if not name.strip():
            continue
        ids = sorted(names.get(normalized_name(name), ()))
        drugs.append({"slot": slot, "name": name, "ddinter_ids": ids,
                      "name_match": "matched_unique" if len(ids) == 1 else "ambiguous" if ids else "unmatched"})
    evidence, candidates = [], []
    for left, right in combinations(drugs, 2):
        pair = {"slots": [left["slot"], right["slot"]], "levels": []}
        if left["name_match"] != "matched_unique" or right["name_match"] != "matched_unique":
            pair["status"] = "ambiguous_name" if "ambiguous" in (left["name_match"], right["name_match"]) else "unmatched_name"
        else:
            ids = tuple(sorted((left["ddinter_ids"][0], right["ddinter_ids"][0])))
            pair["ddinter_ids"] = list(ids)
            item = index.get(ids)
            if ids[0] == ids[1]:
                pair["status"] = "same_ddinter_id"
            elif item is None:
                pair["status"] = "not_in_snapshot"
            else:
                pair.update(levels=sorted(item["levels"]), source_files=sorted(item["source_files"]),
                            source_row_count=item["source_row_count"])
                levels = {normalized_name(level) for level in item["levels"]}
                if len(levels) != 1:
                    pair["status"] = "conflicting_levels"
                elif next(iter(levels)) not in RANK:
                    pair["status"] = "unknown_level"
                else:
                    pair["status"] = "ranked_evidence"
                    pair["rank"] = RANK[next(iter(levels))]
                    candidates.append(pair)
        evidence.append(pair)
    highest = max((pair["rank"] for pair in candidates), default=None)
    winners = [pair for pair in candidates if pair["rank"] == highest]
    selected = winners[0]["slots"] if len(winners) == 1 else "unknown"
    return {"case_id": case["case_id"], "drug_matches": drugs, "pair_evidence": evidence,
            "decision": "unique_highest_retrieved" if len(winners) == 1 else "highest_level_tie" if winners else "no_ranked_evidence",
            "highest_retrieved_rank": highest, "highest_pair_count": len(winners), "target_pair": selected}


def run(source, prepared, output, allow_partial=False):
    if allow_partial and "partial" not in output.name:
        raise ValueError("Partial runs require a separate explicitly partial-named output directory")
    source_manifest = source / ("source.partial.json" if allow_partial else "source.json")
    required = [source_manifest.name] if allow_partial else FILES + [source_manifest.name]
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise ValueError(f"Incomplete DDInter snapshot; no experiment run: {missing}")
    provenance = json.loads(source_manifest.read_text(encoding="utf-8"))
    recorded = {item["filename"]: item for item in provenance["files"]}
    available = [name for name in FILES if name in recorded]
    expected_available = [name for name in FILES if "_R.csv" not in name] if allow_partial else FILES
    if available != expected_available:
        raise ValueError("Manifest differs from the authorized frozen seven-category partial or eight-category complete snapshot")
    for filename in available:
        if not (source / filename).is_file() or digest(source / filename) != recorded[filename]["sha256"]:
            raise ValueError(f"DDInter source manifest/hash mismatch: {filename}")
    source_scope = {"status": "partial_exploratory" if allow_partial else "complete",
                    "expected_categories": list("ABDHLPRV"),
                    "available_categories": [Path(name).stem[-1] for name in available],
                    "missing_categories": [Path(name).stem[-1] for name in FILES if name not in available],
                    "scope_reason": "Frozen before model results based on network availability; no performance-based category selection."}
    manifest = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("presentation", {}).get("variant") != "v2_permuted_drug_names_only":
        raise ValueError("This experiment requires the frozen permuted drug-name-only v2 pilot")
    input_path = prepared / "pilot.inputs.jsonl"
    if digest(input_path) != manifest["frozen_files"][input_path.name]:
        raise ValueError("Frozen pilot input changed")
    inputs = read_jsonl(input_path)
    if len(inputs) != 50 or [row["case_id"] for row in inputs] != manifest["split_ids"]["pilot"]:
        raise ValueError("Expected the unchanged 50-list pilot")
    names, index, source_summary, conflicts = build_index([source / name for name in available])
    evidence = [retrieve(case, names, index) for case in inputs]
    for item in evidence:
        item["source_snapshot_status"] = source_scope["status"]
        item["missing_source_categories"] = source_scope["missing_categories"]
    # Retrieval above reads no reference labels; evaluation is a separate call below.
    responses = [{"case_id": item["case_id"], "response": {"target_pair": item["target_pair"]}} for item in evidence]
    ensure_empty(output)
    write_jsonl(output / "retrieval-evidence.jsonl", evidence)
    write_jsonl(output / "responses.jsonl", responses)
    write_jsonl(output / "source-level-conflicts.jsonl", conflicts)
    run_info = {
        "execution": "deterministic_knowledge_retrieval_baseline", "source": str(source.resolve()),
        "source_manifest_sha256": digest(source_manifest), "script_sha256": digest(Path(__file__)),
        "source_page": provenance.get("source_page"), "source_summary": source_summary, "source_scope": source_scope,
        "policy": ["Casefold and whitespace normalization only; multiple IDs for a name leave its pairs unknown.",
                   "Deduplicate unordered DDInter ID pairs across available manifest-verified category files; retain original Level strings.",
                   "Rank only single nonconflicting known levels: Major > Moderate > Minor; unique highest pair or unknown.",
                   "Missing names/edges and Unknown levels are unresolved, never negative or safe.",
                   "A selected pair is highest only among retrieved rankable evidence; other pairs can remain unresolved.",
                   "DDInter levels are not equated with reference C/D/X classifications."]}
    (output / "run-info.json").write_text(json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8")
    report = evaluate(prepared, output / "responses.jsonl", "pilot", output / "evaluation", output / "run-info.json")
    report["retrieval_summary"] = {
        "drug_name_mentions": dict(Counter(drug["name_match"] for item in evidence for drug in item["drug_matches"])),
        "drug_pair_mentions": dict(Counter(pair["status"] for item in evidence for pair in item["pair_evidence"])),
        "decisions": dict(Counter(item["decision"] for item in evidence)),
        "retrieved_original_levels": dict(Counter(level for item in evidence for pair in item["pair_evidence"] for level in pair["levels"])),
        "source_summary": source_summary}
    report["limitations"].extend(run_info["policy"][-3:])
    report["source_scope"] = source_scope
    if allow_partial:
        report["limitations"].append("Exploratory partial snapshot: R was unavailable. Missing R can change name/edge coverage, highest-level selection and abstention; these are not complete-DDInter results.")
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "source_scope": source_scope, "counts": report["counts"], "metrics": report["metrics"],
                      "retrieval_summary": report["retrieval_summary"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/local/ddinter-public-20261114")
    parser.add_argument("--prepared", type=Path, default=PERMUTED)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-partial", action="store_true", help="Use only the frozen seven-category source.partial.json; never claim complete DDInter coverage")
    args = parser.parse_args()
    output = args.output or ROOT / ("outputs/knowledge/ddinter-lists-partial-v1" if args.allow_partial else "outputs/knowledge/ddinter-lists-v1")
    run(args.source, args.prepared, output, args.allow_partial)
