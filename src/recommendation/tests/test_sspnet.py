import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from src.recommendation.model import SSPNetAdapter
from src.recommendation.prepare import encode_codes, map_medications, adjacency
from src.recommendation.train import metrics


class SSPNetTests(unittest.TestCase):
    def test_unambiguous_mapping_and_audited_ambiguity(self):
        audit = Counter()
        values = map_medications([{"system": "RxNorm", "code": c} for c in ["001", "002", "003"]],
                                 {"001": {"A10A"}, "002": {"A10A", "N02B"}}, audit)
        self.assertEqual(values, ["A10A"])
        self.assertEqual(dict(audit), {"mapped": 1, "ambiguous": 1, "unmapped": 1})

    def test_empty_procedure_is_not_unknown_token(self):
        audit = Counter()
        self.assertEqual(encode_codes([], {"<UNK>": 0}, audit, "procedure"), [])
        self.assertEqual(encode_codes([{"system": "toy", "code": "x"}], {"<UNK>": 0}, audit, "procedure"), [0])
        self.assertEqual(audit["unknown_procedure_codes"], 1)

    def test_ehr_graph_symmetry_and_no_self_edges(self):
        graph = adjacency([[[], [], [0, 1]], [[], [], [1]]], 3)
        np.testing.assert_array_equal(graph, [[0, 1, 0], [1, 0, 0], [0, 0, 0]])

    def test_hand_calculated_metrics_and_empty_prediction(self):
        rows = [{"patient_id": "toy", "target": [0, 1]}]
        ddi = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]])
        result = metrics(rows, np.array([[.9, .1, .8]]), 3, ddi, .5)
        self.assertAlmostEqual(result["jaccard"], 1/3)
        self.assertAlmostEqual(result["f1"], .5)
        self.assertEqual(result["ddi_rate"], 0)
        perfect = metrics(rows, np.array([[.9, .8, .1]]), 3, ddi, .5)
        self.assertEqual(perfect["jaccard"], 1)
        self.assertEqual(perfect["ddi_rate"], 1)
        empty = metrics(rows, np.zeros((1, 3)), 3, ddi, .5)
        self.assertEqual(empty["f1"], 0)
        self.assertEqual(empty["predicted_pairs"], 0)

    def test_normal_import_empty_training_reload_and_no_current_answer(self):
        torch.set_num_threads(1)
        torch.manual_seed(8)
        config = {"dim": 16, "initial_inter": .1, "initial_garm": .1}
        graph = np.zeros((4, 4), dtype=np.float32)
        model = SSPNetAdapter(config, (4, 3, 4), graph, graph, torch.device("cpu"))
        patient = [[[0], [], [1]], [[1], [], []]]
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        initial = model.score_extractor[2].weight.detach().clone()
        scores, penalty = model(patient)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(scores, torch.tensor([[0., 1., 0., 0.]]))+penalty
        loss.backward()
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None))
        optimizer.step()
        self.assertFalse(torch.equal(initial, model.score_extractor[2].weight))
        model.eval()
        with torch.no_grad():
            reference = model(patient)[0]
            patient[-1][2] = [2]
            self.assertTrue(torch.equal(reference, model(patient)[0]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"model.pt"
            torch.save(model.state_dict(), path)
            fresh = SSPNetAdapter(config, (4, 3, 4), graph, graph, torch.device("cpu"))
            fresh.load_state_dict(torch.load(path, weights_only=True)); fresh.eval()
            with torch.no_grad():
                self.assertTrue(torch.equal(reference, fresh(patient)[0]))


if __name__ == "__main__":
    unittest.main()
