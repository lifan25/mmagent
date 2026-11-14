"""Reproduce graph provenance and exploratory baselines without retraining."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations, product
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "src/recommendation/configs/sspnet-synthea-product.json"
OUTPUT = ROOT / "outputs/recommendation/ddi-audit-20261114"


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def class_pairs(left, right):
    return {tuple(sorted((a, b))) for a, b in product(left, right) if a != b}


def last_history_scores(rows, size):
    scores = np.zeros((len(rows), size))
    for i, row in enumerate(rows):
        scores[i, next(v[2] for v in reversed(row["input"][:-1]) if v[2])] = 1
    return scores


def summarize(rows, scores, graph, mapped):
    if not rows:
        return {"samples": 0}
    targets = np.zeros_like(scores, dtype=np.int32)
    for i, row in enumerate(rows):
        targets[i, row["target"]] = 1
    predicted = scores >= .5
    intersection = (targets * predicted).sum(1)
    denom = targets.sum(1) + predicted.sum(1)
    hits = covered = total = 0
    patient_ja = defaultdict(list)
    ja = intersection / (denom - intersection)
    for row, p, j in zip(rows, predicted, ja):
        patient_ja[row["patient_id"]].append(float(j))
        for a, b in combinations(np.flatnonzero(p), 2):
            total += 1
            covered += int(mapped[a, b])
            hits += int(graph[a, b])
    return {"samples": len(rows), "patients": len(patient_ja), "jaccard": float(ja.mean()),
            "patient_macro_jaccard": float(np.mean([np.mean(x) for x in patient_ja.values()])),
            "f1": float((2 * intersection / denom).mean()),
            "recall": float((intersection / targets.sum(1)).mean()),
            "average_precision": float(np.mean([average_precision_score(y, p) for y, p in zip(targets, scores)])),
            "average_predictions": float(predicted.sum(1).mean()), "graph_flagged_pairs": hits,
            "all_predicted_pairs": total, "cid_mapped_pairs": covered, "unmapped_pairs": total-covered,
            "flag_rate_all_pairs": hits/total if total else None,
            "flag_rate_cid_mapped_pairs": hits/covered if covered else None}


def group_summaries(rows, scores, graph, mapped):
    groups = {"all": lambda r: True, "empty_current_procedures": lambda r: r["empty_current_procedures"],
              "recorded_current_procedures": lambda r: not r["empty_current_procedures"],
              "one_history_visit": lambda r: len(r["input"]) == 2,
              "multiple_history_visits": lambda r: len(r["input"]) > 2}
    return {name: summarize([r for r, keep in zip(rows, mask) if keep], scores[mask], graph, mapped)
            for name, check in groups.items() for mask in [np.array([check(r) for r in rows])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output
    if output.exists():
        raise ValueError("Audit output exists; preserve completed audit and use a new version")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    prepared, run, reference = (ROOT/config[k] for k in ("prepared_dir", "run_dir", "reference_dir"))
    vocab = json.loads((prepared/"vocabulary.json").read_text())
    meds = vocab["medications"]
    indices = {code: i for i, code in enumerate(meds)}
    manifest = json.loads((prepared/"manifest.json").read_text())
    chosen_names = {name for _, name in manifest["ddi"]["selected_events"]}
    cid_classes, cid_atc = defaultdict(set), defaultdict(set)
    with (reference/"drug-atc.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            cid_atc[row[0]].update(row[1:])
            cid_classes[row[0]].update(indices[c[:4]] for c in row[1:] if c[:4] in indices)
    graphs = np.load(prepared/"graphs.npz")
    selected = np.zeros_like(graphs["ddi"])
    all_events = np.zeros_like(selected)
    events, witnesses, raw_pairs = Counter(), defaultdict(set), set()
    selected_rows = 0
    unique_selected = set()
    with (reference/"drug-DDI.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            a, b = row["STITCH 1"], row["STITCH 2"]
            event, name = row["Polypharmacy Side Effect"], row["Side Effect Name"]
            events[(event, name)] += 1
            pair = tuple(sorted((a, b)))
            if pair not in raw_pairs:
                raw_pairs.add(pair)
                for i, j in class_pairs(cid_classes[a], cid_classes[b]):
                    all_events[i, j] = all_events[j, i] = 1
            if name not in chosen_names:
                continue
            selected_rows += 1
            unique_selected.add((*pair, event))
            for i, j in class_pairs(cid_classes[a], cid_classes[b]):
                selected[i, j] = selected[j, i] = 1
                witnesses[(i, j)].add((a, b, event, name))
    assert sorted(events, key=lambda k: (events[k], k))[:40] == [tuple(x) for x in manifest["ddi"]["selected_events"]]
    np.testing.assert_array_equal(selected, graphs["ddi"])
    test = read_rows(prepared/"test.jsonl")
    scores = np.load(run/"test-scores.npy")
    flagged = Counter(pair for p in scores >= .5 for pair in combinations(np.flatnonzero(p), 2) if selected[pair])
    edge_details = []
    for (i, j), n in flagged.most_common():
        detail = []
        for a, b, event, name in sorted(witnesses[(i, j)]):
            detail.append({"cid_a": a, "cid_b": b, "event_id": event, "event_name": name,
                           "cid_a_atc": sorted(cid_atc[a]), "cid_b_atc": sorted(cid_atc[b])})
        edge_details.append({"classes": [meds[i], meds[j]], "prediction_occurrences": n,
                             "source_witness_count": len(detail), "source_witnesses": detail})
    data = {s: read_rows(prepared/f"{s}.jsonl") for s in ("train", "validation", "test")}
    frequency = Counter(c for row in data["train"] for c in row["target"])
    k = max(1, int(np.floor(np.mean([len(r["target"]) for r in data["train"]]) + .5)))
    popular = [i for i, _ in sorted(frequency.items(), key=lambda x: (-x[1], x[0]))[:k]]
    comparisons = {}
    for split in ("validation", "test"):
        rows = data[split]
        last = last_history_scores(rows, len(meds))
        pop = np.zeros_like(last)
        pop[:, popular] = 1
        comparisons[split] = {"last_nonempty_history": group_summaries(rows, last, selected, graphs["ddi_mapping_mask"]),
                              "training_popularity_fixed_k": group_summaries(rows, pop, selected, graphs["ddi_mapping_mask"])}
    comparisons["test"]["sspnet_saved_scores"] = group_summaries(test, scores, selected, graphs["ddi_mapping_mask"])
    # Validation inference only; no training or repeated final-test model call.
    import torch
    if __package__:
        from .model import SSPNetAdapter
    else:
        from model import SSPNetAdapter
    torch.set_num_threads(1)
    model = SSPNetAdapter(config, tuple(len(vocab[x]) for x in ("diagnoses", "procedures", "medications")),
                          graphs["ehr"], selected, torch.device("cpu"))
    checkpoint = torch.load(run/"best.pt", map_location="cpu", weights_only=True)
    assert checkpoint["vocabulary"] == vocab
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    with torch.no_grad():
        validation_scores = np.array([torch.sigmoid(model(r["input"])[0]).numpy()[0] for r in data["validation"]])
    comparisons["validation"]["sspnet_best_checkpoint"] = group_summaries(data["validation"], validation_scores, selected, graphs["ddi_mapping_mask"])
    assert np.isclose(comparisons["validation"]["sspnet_best_checkpoint"]["all"]["jaccard"],
                      json.loads((run/"results.json").read_text())["best_validation_jaccard"])
    report = {"date": "2026-11-14", "scope": "Exploratory diagnosis; no new model training or final-test inference",
              "prepared_dir": config["prepared_dir"], "original_run": config["run_dir"],
              "source_rows": sum(events.values()), "event_groups": len(events),
              "unique_unordered_cid_pairs_all_events": len(raw_pairs),
              "selected_rows": selected_rows, "selected_unique_cid_pair_event": len(unique_selected),
              "reproduced_selected_graph": True, "selected_class_edges": int(selected.sum()/2),
              "all_event_class_edges": int(all_events.sum()/2), "top_flagged_class_edges": edge_details,
              "all_events_graph_test_sensitivity": summarize(test, scores, all_events, graphs["ddi_mapping_mask"]),
              "baseline_k_from_train": k, "baseline_popular_classes": [meds[i] for i in popular],
              "comparisons": comparisons,
              "evaluation_notes": "Hard-set baselines use 0/1 scores; AP is a tied two-level ranking. Cohort groups are observational, not causal."}
    output.mkdir(parents=True)
    (output/"results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    np.save(output/"validation-scores.npy", validation_scores)
    print(json.dumps({k: report[k] for k in ("source_rows", "event_groups", "selected_rows", "selected_class_edges", "all_event_class_edges", "baseline_k_from_train")}), flush=True)
    print(json.dumps({s: {m: x["all"] for m, x in v.items()} for s, v in comparisons.items()}, indent=2), flush=True)


if __name__ == "__main__":
    main()
