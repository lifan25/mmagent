"""Prepare the current A1 Synthea cohort for an SSPNet compatibility run."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def rxnorm_mapping(path):
    mapping = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row["RXCUI"] and row["ATC5"]:
                mapping[row["RXCUI"]].add(row["ATC5"][:4])
    return mapping


def product_mapping(snapshot, legacy):
    """Prefer product classification; ingredient-only ambiguity stays unresolved."""
    mapping, decisions = {}, {}
    for code, responses in snapshot["drugs"].items():
        candidates = {}
        for source in ("ATCPROD", "ATC"):
            rows = responses[source].get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])
            candidates[source] = {row["rxclassMinConceptItem"]["classId"][:4] for row in rows
                                  if row["rxclassMinConceptItem"]["classType"] == "ATC1-4"
                                  and (source != "ATCPROD" or row["minConcept"]["rxcui"] == code)}
        source = "ATCPROD" if candidates["ATCPROD"] else "ATC" if candidates["ATC"] else "legacy"
        options = candidates.get(source, legacy.get(code, set()))
        mapping[code] = options
        decisions[code] = {"source": source, "classes": sorted(options),
                           "legacy_classes": sorted(legacy.get(code, set()))}
    return mapping, decisions


def apply_reviewed_crosswalk(mapping, decisions, crosswalk):
    for code, row in crosswalk.items():
        atc3 = row["atc5"][:4]
        if len(mapping[code]) <= 1 or atc3 not in mapping[code]:
            raise ValueError(f"Crosswalk must resolve an existing ambiguity: {code}")
        mapping[code] = {atc3}
        decisions[code].update(source="project ingredient/dose-form crosswalk", classes=[atc3],
                               evidence=row)


def map_medications(items, mapping, audit):
    result = set()
    for item in items:
        if item["system"] != "RxNorm":
            raise ValueError("This entry supports the Synthea RxNorm cohort only")
        options = mapping.get(item["code"], set())
        state = "mapped" if len(options) == 1 else "ambiguous" if options else "unmapped"
        audit[state] += 1
        if state == "mapped":
            result.update(options)
    return sorted(result)


def token(item):
    return item["system"] + "|" + item["code"]


def encode_codes(items, vocabulary, audit, field):
    result = set()
    for item in items:
        key = token(item)
        if key not in vocabulary:
            audit[f"unknown_{field}_codes"] += 1
        result.add(vocabulary.get(key, vocabulary["<UNK>"]))
    return sorted(result)


def adjacency(records, med_size):
    graph = np.zeros((med_size, med_size), dtype=np.float32)
    for visit in records:
        ids = visit[2]
        for i in ids:
            for j in ids:
                if i != j:
                    graph[i, j] = 1
    return graph


def ddi_graph(reference, medications, least_frequent):
    # Follow the upstream literal bottom-TOPK event count selection, not a severity claim.
    counts = Counter()
    with (reference / "drug-DDI.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            counts[(row["Polypharmacy Side Effect"], row["Side Effect Name"])] += 1
    chosen = sorted(counts, key=lambda key: (counts[key], key))[:least_frequent]
    event_names = {name for _, name in chosen}
    cid_codes = defaultdict(set)
    with (reference / "drug-atc.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            for atc in row[1:]:
                if atc[:4] in medications:
                    cid_codes[row[0]].add(medications[atc[:4]])
    graph = np.zeros((len(medications), len(medications)), dtype=np.float32)
    selected_rows = 0
    with (reference / "drug-DDI.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row["Side Effect Name"] not in event_names:
                continue
            selected_rows += 1
            for i in cid_codes.get(row["STITCH 1"], ()):
                for j in cid_codes.get(row["STITCH 2"], ()):
                    if i != j:
                        graph[i, j] = graph[j, i] = 1
    return graph, {"policy": "40 least frequent event groups; deterministic lexical tie break; then filter names",
                   "event_groups": len(chosen), "source_rows": sum(counts.values()),
                   "selected_source_rows": selected_rows, "undirected_edges": int(graph.sum()/2),
                   "selected_events": chosen}


def ddi_mapping_mask(reference, medications):
    with (reference / "drug-atc.csv").open(encoding="utf-8-sig", newline="") as source:
        present = {code[:4] for row in csv.reader(source) for code in row[1:]}
    mapped = np.array([code in present for code in medications], dtype=np.float32)
    mask = np.outer(mapped, mapped)
    np.fill_diagonal(mask, 0)
    return mask, [code for code in medications if code not in present]


def prepare(config):
    source = ROOT / config["a1_dir"]
    reference = ROOT / config["reference_dir"]
    output = ROOT / config["prepared_dir"]
    if output.exists() and any(output.iterdir()):
        raise ValueError("Prepared directory already contains files; use a new version")
    visits = read_jsonl(source / "main_visits.jsonl")
    examples = read_jsonl(source / "main_prediction_examples.jsonl")
    split = json.loads((source / "split.json").read_text())
    memberships = {p: group for group, ids in split.items() for p in ids}
    if sum(map(len, split.values())) != len(memberships):
        raise ValueError("Patient splits overlap")
    if any(v["split"] != memberships[v["patient_id"]] for v in visits):
        raise ValueError("A1 patient split mismatch")
    mapping = rxnorm_mapping(reference / "ndc2atc_level4.csv")
    mapping_info = "Exact RXCUI -> unambiguous four-character ATC level 3; ambiguous/missing excluded and counted"
    decisions = None
    if config.get("mapping_snapshot"):
        snapshot = json.loads((ROOT / config["mapping_snapshot"]).read_text(encoding="utf-8"))
        mapping, decisions = product_mapping(snapshot, mapping)
        mapping_info = {"policy": "ATCPROD first, ATC ingredient fallback, legacy only if both absent; singleton ATC3 only",
                        "snapshot": config["mapping_snapshot"], "retrieved_at": snapshot["retrieved_at"],
                        "versions": snapshot["versions"]}
        if config.get("reviewed_crosswalk"):
            crosswalk = json.loads((ROOT / config["reviewed_crosswalk"]).read_text(encoding="utf-8"))
            apply_reviewed_crosswalk(mapping, decisions, crosswalk)
            mapping_info["project_crosswalk"] = config["reviewed_crosswalk"]
    coverage = Counter()
    mapped_visits = [map_medications(v["medications"], mapping, coverage) for v in visits]
    train = [(v, meds) for v, meds in zip(visits, mapped_visits) if v["split"] == "train"]
    vocab = {
        "diagnoses": ["<UNK>"] + sorted({token(c) for v, _ in train for c in v["diagnoses"]}),
        "procedures": ["<UNK>"] + sorted({token(c) for v, _ in train for c in v["procedures"]}),
        "medications": sorted({code for _, meds in train for code in meds}),
    }
    indices = {key: {value: i for i, value in enumerate(values)} for key, values in vocab.items()}
    def meds_to_ids(items, audit):
        classes = map_medications(items, mapping, audit)
        missing = [code for code in classes if code not in indices["medications"]]
        audit["outside_train_med_vocabulary"] += len(missing)
        return [indices["medications"][code] for code in classes if code in indices["medications"]]
    records, audits = {name: [] for name in split}, {name: Counter() for name in split}
    for example in examples:
        group, case = example["split"], example["case"]
        if memberships[example["patient_id"]] != group:
            raise ValueError("Prediction split mismatch")
        audit = audits[group]
        audit["source_examples"] += 1
        target = meds_to_ids(example["target_medications"], audit)
        history = []
        for visit in case["history"]:
            history.append([encode_codes(visit["diagnoses"], indices["diagnoses"], audit, "diagnosis"),
                            encode_codes(visit["procedures"], indices["procedures"], audit, "procedure"),
                            meds_to_ids(visit["medications"], audit)])
        if not target:
            audit["excluded_empty_mapped_target"] += 1
            continue
        if not any(visit[2] for visit in history):
            audit["excluded_no_mapped_medication_history"] += 1
            continue
        current = [encode_codes(case["diagnoses"], indices["diagnoses"], audit, "diagnosis"),
                   encode_codes(case["procedures"], indices["procedures"], audit, "procedure"), []]
        records[group].append({"patient_id": example["patient_id"], "case_id": case["case_id"],
                               "input": history + [current], "target": target,
                               "empty_current_procedures": not current[1],
                               "empty_history_procedures": any(not v[1] for v in history)})
        audit["retained_examples"] += 1
    for name, rows in records.items():
        if not rows:
            raise ValueError(f"No usable {name} examples after mapping")
    train_records = [[[], [], [indices["medications"][c] for c in meds]] for _, meds in train]
    ehr = adjacency(train_records, len(vocab["medications"]))
    ddi, ddi_info = ddi_graph(reference, indices["medications"], config["ddi_least_frequent_events"])
    if not ddi.any():
        raise ValueError("No DDI edges after mapping: cannot claim safety-loss validation")
    output.mkdir(parents=True, exist_ok=True)
    graphs = {"ehr": ehr, "ddi": ddi}
    if decisions is not None:
        graphs["ddi_mapping_mask"], ddi_info["classes_without_cid_mapping"] = ddi_mapping_mask(reference, vocab["medications"])
        ddi_info["rate_scope"] = "Only pairs with both ATC3 nodes linked to source CIDs; absent edges are not clinical negatives"
    np.savez(output / "graphs.npz", **graphs)
    (output / "vocabulary.json").write_text(json.dumps(vocab, indent=2), encoding="utf-8")
    for name, rows in records.items():
        with (output / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    report = {"source_a1": config["a1_dir"], "a1_manifest": json.loads((source / "manifest.json").read_text(encoding="utf-8")),
              "mapping": mapping_info,
              "visit_medication_occurrence_coverage": dict(coverage), "vocabulary_sizes": {k: len(v) for k, v in vocab.items()},
              "ehr_edges": int(ehr.sum()/2), "ddi": ddi_info,
              "splits": {name: {**dict(audits[name]), "patients": len({r["patient_id"] for r in rows}),
                                 "empty_current_procedures": sum(r["empty_current_procedures"] for r in rows),
                                 "empty_history_procedures": sum(r["empty_history_procedures"] for r in rows)} for name, rows in records.items()}}
    (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if decisions is not None:
        (output / "mapping-decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "a1_manifest"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "configs/sspnet-synthea.json")
    args = parser.parse_args()
    prepare(json.loads(args.config.read_text(encoding="utf-8")))
