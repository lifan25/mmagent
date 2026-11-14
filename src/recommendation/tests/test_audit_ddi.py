"""Hand-computable checks for graph projection and exploratory metrics."""

import unittest

import numpy as np

from src.recommendation.audit_ddi import class_pairs, last_history_scores, summarize


class AuditDDITest(unittest.TestCase):
    def test_projection_deduplicates_and_excludes_self_edges(self):
        self.assertEqual(class_pairs({0, 1}, {0, 1, 2}), {(0, 1), (0, 2), (1, 2)})
        self.assertEqual(class_pairs(set(), {0}), set())

    def test_last_history_never_reads_current_answer(self):
        row = {"input": [[[], [], [0]], [[], [], []], [[], [], [2]]]}
        np.testing.assert_array_equal(last_history_scores([row], 3), [[1, 0, 0]])
        row["input"][-1][2] = [1]
        np.testing.assert_array_equal(last_history_scores([row], 3), [[1, 0, 0]])

    def test_unknown_pairs_and_empty_predictions_are_not_safe(self):
        rows = [{"patient_id": "fictional", "target": [0]}]
        graph = np.zeros((3, 3))
        metrics = summarize(rows, np.array([[1., 1., 0.]]), graph, graph)
        self.assertEqual(metrics["jaccard"], .5)
        self.assertEqual(metrics["f1"], 2/3)
        self.assertEqual(metrics["all_predicted_pairs"], 1)
        self.assertEqual(metrics["unmapped_pairs"], 1)
        self.assertIsNone(metrics["flag_rate_cid_mapped_pairs"])
        empty = summarize(rows, np.zeros((1, 3)), graph, graph)
        self.assertEqual(empty["jaccard"], 0.)
        self.assertIsNone(empty["flag_rate_all_pairs"])


if __name__ == "__main__":
    unittest.main()
