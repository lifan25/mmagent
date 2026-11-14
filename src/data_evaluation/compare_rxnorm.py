"""Compare fixed predictions in a shared space; never choose products using test targets."""

import argparse
import copy
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from src.knowledge.check import check, load_rules
from src.recommendation.prepare import read_jsonl
from .pipeline import ROOT
from .prepare_context import apply_context


def set_scores(predicted, expected):
    overlap = len(predicted & expected)
    return {"jaccard": overlap / len(predicted | expected) if predicted | expected else 1.,
            "f1": 2 * overlap / (len(predicted) + len(expected)) if predicted or expected else 1.}


def train_modes(visits, mapping):
    counts = defaultdict(Counter)
    for visit in visits:
        if visit["split"] != "train":
            continue
        for drug in visit["medications"]:
            options = mapping.get(drug["code"], {}).get("classes", [])
            if len(options) != 1:
                raise ValueError("Comparison requires frozen unambiguous product-to-ATC3 mapping")
            counts[options[0]][drug["code"]] += 1
    return {code: min(freq, key=lambda rx: (-freq[rx], rx)) for code, freq in counts.items()}


def mean_scores(records):
    if not records:
        return {"cases": 0, "jaccard": None, "f1": None}
    return {"cases": len(records), **{k: sum(r[k] for r in records)/len(records) for k in ("jaccard", "f1")}}


def run(fine_dir, without_context_dir, context_path, rules_path, output):
    if output.exists():
        raise ValueError("Preserve old comparison; choose a new directory")
    a1 = ROOT / "data/processed/data_evaluation/synthea-apr2020-v3"
    coarse_dir = ROOT / "outputs/data_evaluation/agent-integration-auto-20261114"
    mapping_path = ROOT / "data/processed/recommendation/synthea-v3-atc3-product-v4/mapping-decisions.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    bridge = json.loads((ROOT / "src/recommendation/resources/rxnorm-cid-v1.json").read_text(encoding="utf-8"))
    modes = train_modes(read_jsonl(a1 / "main_visits.jsonl"), mapping)
    truth = {r["case"]["case_id"]: r for r in read_jsonl(a1 / "main_prediction_examples.jsonl") if r["split"] == "test"}
    def read_run(path):
        rows = read_jsonl(path / "agent-results.jsonl")
        return {r["agent"]["case_id"]: r for r in rows}
    fine, plain, coarse = map(read_run, (fine_dir, without_context_dir, coarse_dir))
    if not set(fine) == set(plain) == set(coarse) == set(truth):
        raise ValueError("Comparison cohorts differ")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    rules = load_rules(rules_path)
    groups = defaultdict(list)
    check_states, coverage, ingredient_pairs = Counter(), Counter(), Counter()
    outputs, paired, unsupported, candidate_counts = [], 0, 0, defaultdict(list)
    def project(codes):
        projected = set()
        for code in codes:
            classes = mapping.get(code, {}).get("classes", [])
            if len(classes) != 1:
                raise ValueError("Unknown/ambiguous fixed ATC3 projection")
            projected.update(classes)
        return projected
    for cid, example in truth.items():
        newer, older = fine[cid]["agent"]["recommendation"], coarse[cid]["agent"]["recommendation"]
        if newer != plain[cid]["agent"]["recommendation"] or fine[cid]["full_scores"] != plain[cid]["full_scores"]:
            raise ValueError("Context or checker changed recommendation")
        target = {r["code"] for r in example["target_medications"]}
        if newer["status"] != "ok" or older["status"] != "ok":
            unsupported += 1
            continue
        paired += 1
        new_pred = {r["drug"]["code"] for r in newer["candidates"]}
        for left, right in combinations(sorted(new_pred), 2):
            ingredient_pairs["all_predicted_product_pairs"] += 1
            if bridge["mapping_complete"][left] and bridge["mapping_complete"][right]:
                a, b = set(bridge["drug_cids"][left]), set(bridge["drug_cids"][right])
                ingredient_pairs["complete_mapping_product_pairs"] += 1
                ingredient_pairs["same_single_cid_product_pairs"] += len(a) == len(b) == 1 and a == b
                ingredient_pairs["overlapping_cid_product_pairs"] += bool(a & b)
        coarse_pred = {r["drug"]["code"] for r in older["candidates"]}
        mode_pred = {modes[code] for code in coarse_pred}
        predictions = {"rxnorm_model": (new_pred, target), "coarse_plus_train_mode": (mode_pred, target),
                       "rxnorm_projected_atc3": (project(new_pred), project(target)),
                       "original_atc3": (coarse_pred, project(target))}
        for name, (pred, expected) in predictions.items():
            groups[name].append(set_scores(pred, expected))
            candidate_counts[name].append(len(pred))
        # This is an explicit prediction baseline, not a factual reverse ATC lookup.
        rec = copy.deepcopy(older)
        mode_scores = {modes[item["drug"]["code"]]: item["score"] for item in older["candidates"]}
        rec.update(model_version="atc3-frozen-plus-training-visit-product-mode-v1",
                   execution="model_inference", candidates=[{"drug": {"system": "RxNorm", "code": code},
                       "score": mode_scores[code]} for code in sorted(mode_pred)])
        # Baseline ranking scores inherit the chosen category score; no product calibration is claimed.
        checked = check(apply_context(example["case"], context), rec, rules)
        check_states[checked["status"]] += 1
        for field in ("checked_rule_count", "pending_rule_count", "checked_candidate_count"):
            coverage[field] += checked["coverage"][field]
        outputs.append({"case_id": cid, "baseline": rec, "check_report": checked})
    summary = {"input_cases": len(truth), "paired_supported_cases": paired, "outside_paired_support": unsupported,
               "predictions_unchanged_with_context": True,
               "mode_policy": "Most frequent original RxCUI per fixed ATC3 among training main_visits; lexical tie break; no test targets.",
               "train_mode_products": modes,
               "same_case_comparison": {name: {**mean_scores(rows),
                   "average_predicted_items": sum(candidate_counts[name])/len(rows)} for name, rows in groups.items()},
               "coarse_mode_check_statuses": dict(check_states), "coarse_mode_check_coverage": dict(coverage),
               "fine_predicted_ingredient_pair_audit": dict(ingredient_pairs),
               "limitations": ["Exploratory one-seed adaptation; label space, graph and validation input policy changed.",
                               "ATC3 projection measures a common coarse task, not exact-product correctness.",
                               "A training-mode product is a baseline prediction, not known identity of a coarse category.",
                               "Checks have no independent clinical correctness labels; context is retrospective."]}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "baseline-checks.jsonl").open("x", encoding="utf-8") as stream:
        for row in outputs:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "train_mode_products"}, indent=2))
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fine-run", type=Path, required=True)
    p.add_argument("--without-context-run", type=Path, required=True)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--rules", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.fine_run, a.without_context_run, a.context, a.rules, a.output)
