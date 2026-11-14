import unittest

import numpy as np
import torch

from src.recommendation.probe_ddi_loss import ddi_penalty, pair_policy


class DDILossProbeTests(unittest.TestCase):
    def test_symmetric_single_edge_has_product_not_degree_weight(self):
        # p=(.2,.8,.5), one edge: .001*.2*.8=.00016, third logit disconnected.
        logits = torch.logit(torch.tensor([[.2, .8, .5]], dtype=torch.float64)).requires_grad_(True)
        graph = torch.tensor([[0., 1., 0.], [1., 0., 0.], [0., 0., 0.]], dtype=torch.float64)
        loss = ddi_penalty(logits, graph)
        self.assertAlmostEqual(loss.item(), .00016)
        gradient = torch.autograd.grad(loss, logits)[0]
        torch.testing.assert_close(gradient, torch.tensor([[.000128, .000032, 0.]], dtype=torch.float64))

    def test_zero_graph_and_unknown_denominator(self):
        logits = torch.zeros((1, 3), dtype=torch.float64, requires_grad=True)
        loss = ddi_penalty(logits, torch.zeros((3, 3), dtype=torch.float64))
        self.assertEqual(loss.item(), 0)
        self.assertEqual(torch.autograd.grad(loss, logits)[0].abs().sum().item(), 0)
        config = {"coef": 2.5, "target_ddi": .06}
        graph = np.zeros((3, 3))
        for predicted, pairs in ((np.array([False, False, False]), 0),
                                 (np.array([True, False, False]), 0),
                                 (np.array([True, True, False]), 1)):
            result = pair_policy(predicted, graph, graph, config)
            self.assertEqual(result["unknown_pairs"], pairs)
            self.assertIsNone(result["cid_mapped_policy"]["rate"])
            self.assertEqual(result["cid_mapped_policy"]["training_rate"], 0)
            self.assertEqual(result["cid_mapped_policy"]["beta"], 1)

    def test_same_predictions_different_denominators_change_beta(self):
        graph = np.array([[0., 1., 0.], [1., 0., 0.], [0., 0., 0.]])
        result = pair_policy(np.ones(3, dtype=bool), graph, graph, {"coef": 2.5, "target_ddi": .06})
        self.assertEqual(result["all_pairs_policy"]["rate"], 1/3)
        self.assertEqual(result["cid_mapped_policy"]["rate"], 1)
        self.assertEqual(result["unknown_pairs"], 2)
        self.assertLess(result["cid_mapped_policy"]["beta"], result["all_pairs_policy"]["beta"])


if __name__ == "__main__":
    unittest.main()
