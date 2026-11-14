"""Read-only checkpoint probe of DDI loss and logits gradients; never trains."""

import argparse
import hashlib
import json
import math
import platform
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .model import SSPNetAdapter
from .prepare import read_jsonl
from .train import ddi_counts

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SEED = 20261114
SAMPLE_COUNT = 32
FD_STEP = 1e-5


def ddi_penalty(logits, adjacency):
    probabilities = torch.sigmoid(logits).reshape(-1)
    return .0005 * probabilities @ adjacency @ probabilities


def pair_policy(predicted, adjacency, mapping_mask, config):
    interactions, all_pairs = ddi_counts(predicted, adjacency)
    _, mapped_pairs = ddi_counts(predicted, adjacency, mapping_mask)
    result = {"interactions": interactions, "all_pairs": all_pairs,
              "mapped_pairs": mapped_pairs, "unknown_pairs": all_pairs-mapped_pairs}
    for name, pairs in (("all_pairs", all_pairs), ("cid_mapped", mapped_pairs)):
        # Match training's zero-denominator fallback, but retain an undefined reporting rate.
        rate = interactions / pairs if pairs else 0.
        beta = (1. if rate <= config["target_ddi"] else
                min(math.exp(config["coef"]*(1-rate/config["target_ddi"])), 1.))
        result[name + "_policy"] = {"rate": interactions / pairs if pairs else None,
                                   "training_rate": rate, "beta": beta}
    return result


def describe(values):
    values = np.asarray(values, dtype=float)
    quantiles = np.quantile(values, [0, .25, .5, .75, 1])
    return {"count": len(values), "mean": float(values.mean()),
            **dict(zip(["min", "p25", "median", "p75", "max"], map(float, quantiles)))}


def run(checkpoint_path, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory; existing probe evidence is preserved")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(SAMPLE_SEED)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    prepared = ROOT / config["prepared_dir"]
    vocabulary = json.loads((prepared / "vocabulary.json").read_text(encoding="utf-8"))
    if checkpoint["vocabulary"] != vocabulary:
        raise ValueError("Checkpoint/prepared vocabulary mismatch")
    graphs = np.load(prepared / "graphs.npz")
    ehr, adjacency, mapping_mask = graphs["ehr"], graphs["ddi"], graphs["ddi_mapping_mask"]
    assert np.array_equal(adjacency, adjacency.T) and not np.diag(adjacency).any()
    assert np.all((adjacency == 0) | (adjacency == 1)) and np.all(adjacency <= mapping_mask)
    sizes = tuple(len(vocabulary[key]) for key in ("diagnoses", "procedures", "medications"))
    assert sizes[2] == 38, "This probe is specified for the fixed 38-class checkpoint"
    rows = read_jsonl(prepared / "train.jsonl")
    indices = random.Random(SAMPLE_SEED).sample(range(len(rows)), SAMPLE_COUNT)
    model = SSPNetAdapter(config, sizes, ehr, adjacency, torch.device("cpu"))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    before = {key: value.clone() for key, value in model.state_dict().items()}
    adjacency64 = torch.tensor(adjacency, dtype=torch.float64)
    checks = {"upstream_value_max_abs_error": 0., "upstream_logits_gradient_max_abs_error": 0.,
              "finite_difference_max_abs_error": 0., "finite_difference_coordinates": 0}
    measurements = []
    for index in indices:
        row = rows[index]
        scores, upstream_loss = model(row["input"])
        actual_gradient = torch.autograd.grad(upstream_loss, scores)[0].detach().double()
        logits = scores.detach().double().requires_grad_(True)
        penalty = ddi_penalty(logits, adjacency64)
        gradient = torch.autograd.grad(penalty, logits)[0]
        np.testing.assert_allclose(upstream_loss.item(), penalty.item(), rtol=2e-6, atol=1e-9)
        torch.testing.assert_close(actual_gradient, gradient, rtol=2e-5, atol=2e-9)
        checks["upstream_value_max_abs_error"] = max(checks["upstream_value_max_abs_error"],
                                                     abs(upstream_loss.item()-penalty.item()))
        checks["upstream_logits_gradient_max_abs_error"] = max(
            checks["upstream_logits_gradient_max_abs_error"], (actual_gradient-gradient).abs().max().item())
        finite_difference = torch.empty_like(logits)
        for column in range(sizes[2]):
            positive, negative = logits.detach().clone(), logits.detach().clone()
            positive[0, column] += FD_STEP
            negative[0, column] -= FD_STEP
            finite_difference[0, column] = (ddi_penalty(positive, adjacency64) -
                                            ddi_penalty(negative, adjacency64)) / (2*FD_STEP)
        torch.testing.assert_close(gradient, finite_difference, rtol=2e-5, atol=1e-9)
        checks["finite_difference_max_abs_error"] = max(
            checks["finite_difference_max_abs_error"], (gradient-finite_difference).abs().max().item())
        checks["finite_difference_coordinates"] += logits.numel()
        target = torch.zeros_like(logits)
        target[0, row["target"]] = 1.
        margin_target = torch.full(logits.shape, -1, dtype=torch.long)
        margin_target[0, :len(row["target"]) ] = torch.tensor(row["target"])
        supervised = .95*F.binary_cross_entropy_with_logits(logits, target) + \
                     .05*F.multilabel_margin_loss(torch.sigmoid(logits), margin_target)
        supervised_gradient = torch.autograd.grad(supervised, logits)[0]
        predicted = torch.sigmoid(scores.detach()).numpy()[0] >= config["threshold"]
        item = pair_policy(predicted, adjacency, mapping_mask, config)
        item.update(supervised_loss=supervised.item(), ddi_loss=penalty.item(),
                    supervised_logits_gradient_l2=supervised_gradient.norm().item(),
                    ddi_logits_gradient_l2=gradient.norm().item())
        for policy in ("all_pairs_policy", "cid_mapped_policy"):
            beta = item[policy]["beta"]
            item[policy]["weighted_supervised_logits_gradient_l2"] = (beta*supervised_gradient).norm().item()
            item[policy]["weighted_ddi_logits_gradient_l2"] = ((1-beta)*gradient).norm().item()
        measurements.append(item)
    checks["model_state_unchanged"] = all(torch.equal(value, model.state_dict()[key]) for key, value in before.items())
    checks["parameter_gradients_unpopulated"] = all(parameter.grad is None for parameter in model.parameters())
    assert checks["model_state_unchanged"] and checks["parameter_gradients_unpopulated"]
    totals = {key: sum(item[key] for item in measurements)
              for key in ("interactions", "all_pairs", "mapped_pairs", "unknown_pairs")}
    policies = {}
    for policy, denominator in (("all_pairs_policy", "all_pairs"), ("cid_mapped_policy", "mapped_pairs")):
        entries = [item[policy] for item in measurements]
        rates = [item["rate"] for item in entries if item["rate"] is not None]
        policies[policy] = {
            "pooled_rate": totals["interactions"]/totals[denominator] if totals[denominator] else None,
            "defined_case_rate_distribution": describe(rates) if rates else None,
            "zero_denominator_cases": sum(item["rate"] is None for item in entries),
            "beta_distribution": describe([item["beta"] for item in entries]),
            "beta_equals_one_cases": sum(item["beta"] == 1 for item in entries),
            "beta_below_0_01_cases": sum(item["beta"] < .01 for item in entries),
            "beta_below_1e_6_cases": sum(item["beta"] < 1e-6 for item in entries),
            **{key: describe([item[key] for item in entries]) for key in
               ("weighted_supervised_logits_gradient_l2", "weighted_ddi_logits_gradient_l2")}}
    def revision(path):
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"repository_commit": revision(ROOT), "sspnet_commit": revision(ROOT / "third_party/SSPNet"),
                   "probe_sha256": digest(Path(__file__)), "checkpoint": checkpoint_path.relative_to(ROOT).as_posix(),
                   "checkpoint_sha256": digest(checkpoint_path), "checkpoint_epoch": checkpoint["epoch"],
                   "training_file": (prepared / "train.jsonl").relative_to(ROOT).as_posix(),
                   "training_sha256": digest(prepared / "train.jsonl"), "graphs_sha256": digest(prepared / "graphs.npz")},
        "checkpoint_config": config,
        "probe_config": {"sample_seed": SAMPLE_SEED, "sample_count": SAMPLE_COUNT, "sampling": "Python random.sample without replacement from train row order",
                         "train_rows": len(rows), "device": "cpu", "threads": torch.get_num_threads(),
                         "model_mode": "eval", "upstream_dtype": "float32", "formula_gradient_dtype": "float64",
                         "finite_difference_step": FD_STEP, "python": platform.python_version(), "torch": torch.__version__},
        "checks": checks, "pair_totals": totals, "policies": policies,
        "losses_and_logits_gradients": {key: describe([item[key] for item in measurements]) for key in
                                        ("supervised_loss", "ddi_loss", "supervised_logits_gradient_l2", "ddi_logits_gradient_l2")},
        "limitations": ["Fixed best-checkpoint eval-mode diagnostic on 32 training examples; not historical training trajectories.",
                        "Gradients are with respect to logits, not model parameters; beta is detached as in training.",
                        "Finite differences validate the float64 quadratic formula; actual upstream float32 loss and logits gradients are compared separately.",
                        "CID mapping support is not clinical evidence coverage. Zero denominators are undefined in reports but training uses zero.",
                        "No optimizer, backward-to-parameters, parameter update, retraining or test-set access."]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output / "results.json"), "checks": checks, "pair_totals": totals,
                      "policies": policies}, indent=2, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "outputs/recommendation/sspnet-synthea-v3-product-cpu-seed8/best.pt")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/recommendation/ddi-loss-probe-20261114")
    args = parser.parse_args()
    run(args.checkpoint.resolve(), args.output.resolve())
