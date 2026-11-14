"""Train all mapped examples, select on validation, reload and test once."""

import argparse
import json
import math
import os
import random
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import average_precision_score

if __package__:
    from .model import SSPNetAdapter
    from .prepare import read_jsonl
else:
    from model import SSPNetAdapter
    from prepare import read_jsonl

ROOT = Path(__file__).resolve().parents[2]


def ddi_counts(predicted, ddi, mapping_mask=None):
    ids = np.flatnonzero(predicted)
    possible = (len(ids)*(len(ids)-1)//2 if mapping_mask is None else
                int(np.triu(mapping_mask[np.ix_(ids, ids)], 1).sum()))
    return int(np.triu(ddi[np.ix_(ids, ids)], 1).sum()), possible


def metrics(rows, probabilities, size, ddi, threshold, mapping_mask=None):
    if not rows:
        return {"samples": 0}
    labels = np.zeros((len(rows), size), dtype=np.int32)
    for i, row in enumerate(rows):
        labels[i, row["target"]] = 1
    fine = any("outside_train_target_codes" in row for row in rows)
    available = np.array([row.get("input_supported", True) for row in rows], dtype=bool)
    probabilities = np.asarray(probabilities)
    if probabilities.shape != (len(rows), size) or not np.isfinite(probabilities[available]).all():
        raise ValueError("Scores must be aligned and finite for every supported input")
    predicted = (probabilities >= threshold) & available[:, None]
    intersection = (predicted * labels).sum(axis=1)
    outside = np.array([len(set(row.get("outside_train_target_codes", []))) for row in rows])
    target_counts, pred_counts = labels.sum(axis=1) + outside, predicted.sum(axis=1)
    if np.any(target_counts == 0):
        raise ValueError("An evaluation target must include at least one original medication")
    ja = intersection / (target_counts + pred_counts - intersection)
    f1 = 2*intersection / (target_counts + pred_counts)
    ap_eligible = available & (outside == 0)
    ap = np.full(len(rows), np.nan)
    for i in np.flatnonzero(ap_eligible):
        ap[i] = average_precision_score(labels[i], probabilities[i])
    patient_values = defaultdict(list)
    interactions = pairs = 0
    for row, j, f, a, pred in zip(rows, ja, f1, ap, predicted):
        patient_values[row["patient_id"]].append([j, f, a])
        n, d = ddi_counts(pred, ddi, mapping_mask)
        interactions += n
        pairs += d
    patient_ja_f1 = np.mean([np.mean(np.asarray(values)[:, :2], axis=0)
                             for values in patient_values.values()], axis=0)
    patient_ap = [float(np.mean([v[2] for v in values if np.isfinite(v[2])]))
                  for values in patient_values.values() if any(np.isfinite(v[2]) for v in values)]
    total_pairs = sum(int(p.sum())*(int(p.sum())-1)//2 for p in predicted)
    report = {"samples": len(rows), "patients": len(patient_values), "jaccard": float(ja.mean()),
            "f1": float(f1.mean()), "prauc_average_precision": float(ap[ap_eligible].mean()) if ap_eligible.any() else None,
            "average_medications": float(pred_counts.mean()),
            "ddi_rate": interactions/pairs if pairs else (None if mapping_mask is not None else 0.),
            "ddi_pairs": interactions, "predicted_pairs": pairs,
            "total_predicted_pairs": total_pairs, "unmapped_predicted_pairs": total_pairs-pairs,
            "ddi_mapping_pair_coverage": pairs / total_pairs if total_pairs else None,
            "ddi_rate_scope": "CID-mapped pairs" if mapping_mask is not None else "all pairs (legacy)",
            "patient_macro": {"jaccard": float(patient_ja_f1[0]), "f1": float(patient_ja_f1[1]),
                              "prauc_average_precision": float(np.mean(patient_ap)) if patient_ap else None}}
    if fine:
        report.update(target_scope="All original RxCUI targets; unseen target labels count as false negatives",
            input_supported_samples=int(available.sum()), input_rejected_samples=int((~available).sum()),
            recommendation_coverage=float(available.mean()),
            outside_train_target_occurrences=int(outside.sum()),
            targets_not_fully_representable=int((outside > 0).sum()),
            ap_evaluable_samples=int(ap_eligible.sum()), ap_case_coverage=float(ap_eligible.mean()),
            ap_evaluable_patients=len(patient_ap),
            ap_scope="Supported inputs whose entire original target is inside the training vocabulary; no scores invented for OOV labels or nonanswers",
            ddi_rate_scope="Pairs of original products with complete unique ingredient-CID mappings")
    return report


def evaluate(model, rows, size, ddi, threshold, mapping_mask=None):
    model.eval()
    scores = []
    with torch.no_grad():
        for row in rows:
            if not row.get("input_supported", True):
                scores.append(np.full(size, np.nan, dtype=np.float32))
                continue
            output, loss_ddi = model(row["input"])
            if not torch.isfinite(output).all() or not torch.isfinite(loss_ddi):
                raise FloatingPointError("Nonfinite evaluation output")
            scores.append(torch.sigmoid(output).cpu().numpy()[0])
    probabilities = np.asarray(scores)
    report = {"overall": metrics(rows, probabilities, size, ddi, threshold, mapping_mask)}
    for name, predicate in {
        "empty_current_procedures": lambda r: r["empty_current_procedures"],
        "nonempty_current_procedures": lambda r: not r["empty_current_procedures"],
        "empty_history_procedures": lambda r: r["empty_history_procedures"],
        "both_current_and_history_empty": lambda r: r["empty_current_procedures"] and r["empty_history_procedures"],
    }.items():
        mask = np.array([predicate(r) for r in rows])
        report[name] = metrics([r for r, keep in zip(rows, mask) if keep], probabilities[mask], size, ddi, threshold, mapping_mask)
    return report, probabilities


def run(config):
    seed = config["seed"]
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    device = torch.device(config["device"])
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Configured CUDA is unavailable; choose CPU explicitly")
    prepared, output = ROOT/config["prepared_dir"], ROOT/config["run_dir"]
    if output.exists() and any(output.iterdir()):
        raise ValueError("Run directory is nonempty; use a new run version")
    output.mkdir(parents=True, exist_ok=True)
    vocab = json.loads((prepared/"vocabulary.json").read_text())
    graph = np.load(prepared/"graphs.npz")
    ehr, ddi = graph["ehr"], graph["ddi"]
    mapping_mask = graph["ddi_mapping_mask"] if "ddi_mapping_mask" in graph else None
    data = {name: read_jsonl(prepared/f"{name}.jsonl") for name in ["train", "validation", "test"]}
    if any(not row.get("input_supported", True) or row.get("outside_train_target_codes") for row in data["train"]):
        raise ValueError("Training inputs and labels must all belong to the training vocabulary")
    sizes = tuple(len(vocab[key]) for key in ["diagnoses", "procedures", "medications"])
    model = SSPNetAdapter(config, sizes, ehr, ddi, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["lr"])
    initial = model.score_extractor[2].weight.detach().clone()
    history, best_score, best_epoch = [], -1., None
    checks = {"train_steps": 0, "empty_current_train_steps": 0, "empty_history_train_steps": 0,
              "empty_current_parameter_update_verified": False}
    start = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    for epoch in range(1, config["epochs"]+1):
        model.train()
        order = list(range(len(data["train"])))
        random.shuffle(order)
        losses = []
        epoch_start = time.perf_counter()
        for step, index in enumerate(order, 1):
            row = data["train"][index]
            target = torch.zeros((1, sizes[2]), device=device)
            target[0, row["target"]] = 1.
            margin_target = -torch.ones((1, sizes[2]), dtype=torch.long, device=device)
            margin_target[0, :len(row["target"])] = torch.tensor(row["target"], device=device)
            output_scores, loss_ddi = model(row["input"])
            if not torch.isfinite(output_scores).all() or not torch.isfinite(loss_ddi):
                raise FloatingPointError("Nonfinite training output")
            supervised = .95*F.binary_cross_entropy_with_logits(output_scores, target) + \
                         .05*F.multilabel_margin_loss(torch.sigmoid(output_scores), margin_target)
            prediction = torch.sigmoid(output_scores).detach().cpu().numpy()[0] >= config["threshold"]
            n, d = ddi_counts(prediction, ddi, mapping_mask)
            rate = n/d if d else 0.
            if rate <= config["target_ddi"]:
                loss = supervised
            else:
                beta = min(math.exp(config["coef"]*(1-rate/config["target_ddi"])), 1.)
                loss = beta*supervised + (1-beta)*loss_ddi
            if not torch.isfinite(loss):
                raise FloatingPointError("Nonfinite training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float("inf"), error_if_nonfinite=True)
            verify = row["empty_current_procedures"] and not checks["empty_current_parameter_update_verified"]
            before = model.score_extractor[2].weight.detach().clone() if verify else None
            optimizer.step()
            if verify:
                checks["empty_current_parameter_update_verified"] = not torch.equal(before, model.score_extractor[2].weight)
            checks["train_steps"] += 1
            checks["empty_current_train_steps"] += row["empty_current_procedures"]
            checks["empty_history_train_steps"] += row["empty_history_procedures"]
            losses.append(loss.item())
            if step % 200 == 0:
                print(json.dumps({"epoch": epoch, "step": step, "total": len(order),
                                  "seconds": round(time.perf_counter()-epoch_start, 2)}), flush=True)
        validation, _ = evaluate(model, data["validation"], sizes[2], ddi, config["threshold"], mapping_mask)
        entry = {"epoch": epoch, "loss": float(np.mean(losses)), "validation": validation,
                 "seconds": time.perf_counter()-epoch_start}
        history.append(entry)
        print(json.dumps(entry), flush=True)
        with (output/"history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry)+"\n")
        if validation["overall"]["jaccard"] > best_score:
            best_score, best_epoch = validation["overall"]["jaccard"], epoch
            torch.save({"state_dict": model.state_dict(), "epoch": epoch, "config": config,
                        "vocabulary": vocab}, output/"best.pt")
    checks["parameters_changed"] = not torch.equal(initial, model.score_extractor[2].weight)
    # Compare save/load using validation only, keeping final test untouched until selection.
    checkpoint = torch.load(output/"best.pt", map_location=device, weights_only=True)
    if checkpoint["vocabulary"] != vocab:
        raise ValueError("Checkpoint vocabulary mismatch")
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    reload_example = next(row for row in data["validation"] if row.get("input_supported", True))
    with torch.no_grad():
        before_reload = model(reload_example["input"])[0].clone()
    fresh = SSPNetAdapter(config, sizes, ehr, ddi, device)
    fresh.load_state_dict(checkpoint["state_dict"])
    fresh.eval()
    with torch.no_grad():
        after_reload = fresh(reload_example["input"])[0]
    checks["reload_equal"] = torch.equal(before_reload, after_reload)
    if not all(checks[k] for k in ["parameters_changed", "empty_current_parameter_update_verified", "reload_equal"]):
        raise AssertionError(checks)
    test, probabilities = evaluate(fresh, data["test"], sizes[2], ddi, config["threshold"], mapping_mask)
    np.save(output/"test-scores.npy", probabilities)
    if config.get("medication_space") == "RxNorm":
        np.save(output/"test-score-available.npy", np.array([r["input_supported"] for r in data["test"]], dtype=bool))
    with (output/"test-predictions.jsonl").open("w", encoding="utf-8") as f:
        for row, scores in zip(data["test"], probabilities):
            prediction = {"case_id": row["case_id"], "patient_id": row["patient_id"], "target": row["target"],
                          "predicted": np.flatnonzero(scores >= config["threshold"]).tolist() if row.get("input_supported", True) else None}
            if config.get("medication_space") == "RxNorm":
                prediction.update(input_supported=row["input_supported"],
                    outside_train_target_codes=row["outside_train_target_codes"],
                    target_medication_codes=row["target_medication_codes"])
            f.write(json.dumps(prediction)+"\n")
    report = {"config": config, "device": str(device), "torch": torch.__version__,
              "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
              "epochs_completed": len(history), "best_epoch": best_epoch, "best_validation_jaccard": best_score,
              "threshold": config["threshold"], "test_evaluations": 1, "test": test, "checks": checks,
              "seconds": time.perf_counter()-start,
              "peak_gpu_memory_mb": torch.cuda.max_memory_allocated()/1024**2 if device.type == "cuda" else None,
              "parameters": sum(p.numel() for p in model.parameters())}
    (output/"results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parent/"configs/sspnet-synthea.json")
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding="utf-8")))
