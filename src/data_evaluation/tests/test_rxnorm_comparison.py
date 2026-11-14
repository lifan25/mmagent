import unittest

from src.data_evaluation.compare_rxnorm import set_scores, train_modes


class ComparisonTests(unittest.TestCase):
    def test_unseen_target_is_missed_not_deleted(self):
        self.assertEqual(set_scores({"known"}, {"known", "unseen"}), {"jaccard": .5, "f1": 2/3})
        self.assertEqual(set_scores(set(), {"unseen"}), {"jaccard": 0., "f1": 0.})

    def test_mode_uses_training_only_and_fixed_tie_break(self):
        mapping = {c: {"classes": ["A"]} for c in ("p1", "p2", "p3")}
        visits = [{"split": "train", "medications": [{"code": "p1"}, {"code": "p2"}]}]
        visits += [{"split": "test", "medications": [{"code": "p3"}]} for _ in range(8)]
        self.assertEqual(train_modes(visits, mapping), {"A": "p1"})


if __name__ == "__main__":
    unittest.main()
