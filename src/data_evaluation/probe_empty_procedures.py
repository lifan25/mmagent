"""Isolated execution of upstream SSPNet classes, without its unused GNN imports."""

import ast
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/SSPNet/src/modules"
sys.dont_write_bytecode = True


def load_file(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_classes():
    sets, layers = load_file("SetTransformer"), load_file("layers")
    environment = {"torch": torch, "nn": nn, "F": F, "np": np, "math": math,
                   "GraphConvolution": layers.GraphConvolution,
                   **{name: getattr(sets, name) for name in ["SAB", "PMA", "MAB", "Encoder_SAB"]}}
    path = SOURCE / "MoleRec.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Keep original class bodies; avoid unused imports requiring torch_geometric.
    classes = ast.Module(body=[node for node in tree.body if isinstance(node, ast.ClassDef)], type_ignores=[])
    exec(compile(classes, str(path), "exec"), environment)
    return environment["SSPNetModel"]


def main():
    model_type = load_classes()
    results = []
    for label, proc_sets in [
        ("baseline", [[1], [2]]),
        ("empty_current", [[1], []]),
        ("empty_history", [[], [2]]),
        ("empty_both", [[], []]),
        ("single_visit_empty", [[]]),
    ]:
        torch.manual_seed(8)
        model = model_type(16, [5, 4, 6], np.zeros((6, 6)), torch.zeros(6, 6))
        # Upstream creates two scalars from uninitialized memory; fix fixture values.
        with torch.no_grad():
            model.inter.fill_(0.1)
            model.garm.fill_(0.1)
        # Disable diagnostic TSNE/plot writes, not any prediction computation.
        model.visual = lambda *args: None
        patient = [[[0, 1], proc, [1] if i < len(proc_sets)-1 else []]
                   for i, proc in enumerate(proc_sets)]
        model.eval()
        med = torch.arange(6)
        scores, ddi_loss = model(med, patient, None, torch.zeros(6, 6))
        assert scores.shape == (1, 6), (label, scores.shape)
        assert torch.isfinite(scores).all() and torch.isfinite(ddi_loss)
        target = torch.tensor([[0., 1., 0., 1., 0., 0.]])
        loss = F.binary_cross_entropy_with_logits(scores, target) + ddi_loss
        loss.backward()
        grads = [p.grad for p in model.parameters() if p.grad is not None]
        assert grads and all(torch.isfinite(g).all() for g in grads), label
        # Current answer is only referenced by the disabled plotting code.
        patient[-1][2] = [2, 3]
        changed, _ = model(med, patient, None, torch.zeros(6, 6))
        assert torch.equal(scores.detach(), changed), label
        model.zero_grad(set_to_none=True)
        model.train()
        training_scores, training_ddi = model(med, patient, None, torch.zeros(6, 6))
        training_loss = F.binary_cross_entropy_with_logits(training_scores, target) + training_ddi
        assert torch.isfinite(training_scores).all() and torch.isfinite(training_loss)
        training_loss.backward()
        assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
        results.append({"case": label, "shape": list(scores.shape), "finite_forward": True,
                        "finite_backward": True, "train_mode_finite_forward_backward": True,
                        "current_answer_independent": True})
    report = {"torch": torch.__version__, "device": "cpu", "seed": 8,
              "source": "third_party/SSPNet/src/modules/MoleRec.py",
              "scope": "original class bodies and actual SetTransformer/layers; unused imports bypassed; visual disabled; inter/garm fixed for fixture; not package/training validation",
              "results": results}
    output = ROOT / "outputs/data_evaluation/sspnet-empty-procedures.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
