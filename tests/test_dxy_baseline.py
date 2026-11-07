import unittest

from src.knowledge.diaformer_baseline import prediction_metrics, split_training, tokenize


class BaselineProtocolTests(unittest.TestCase):
    def test_empty_symptom_training_case_is_skipped_like_upstream_preprocessing(self):
        record = {"disease_tag": "a", "goal": {
            "explicit_inform_slots": {}, "implicit_inform_slots": {},
        }}
        self.assertEqual(tokenize([record], None), [])

    def test_stratified_split_is_disjoint_reproducible_and_keeps_both_classes(self):
        records = [{"disease_tag": name} for name in ("a", "b") for _ in range(10)]
        train, validation = split_training(records, 8)
        self.assertEqual((len(train), len(validation)), (16, 4))
        self.assertFalse(set(train) & set(validation))
        self.assertEqual(set(train) | set(validation), set(range(20)))
        self.assertEqual((train, validation), split_training(records, 8))
        self.assertEqual({records[index]["disease_tag"] for index in validation}, {"a", "b"})

    def test_interactive_metrics_count_negative_symptoms_and_unsuccessful_questions(self):
        metrics = prediction_metrics([
            {"pred_disease": "a", "target_disease": "a", "explicit_symptoms": {"e": True},
             "implicit_symptoms": {"i": True, "j": False}, "inquiry_symptom": ["i", "unknown"]},
            {"pred_disease": "a", "target_disease": "b", "explicit_symptoms": {"e": True},
             "implicit_symptoms": {"j": True}, "inquiry_symptom": ["j"]},
        ])
        self.assertEqual(metrics["correct_cases"], 1)
        self.assertEqual(metrics["diagnosis_accuracy"], 0.5)
        self.assertAlmostEqual(metrics["symptom_recall"], 2 / 3)
        self.assertAlmostEqual(metrics["symptom_precision"], 2 / 3)
        self.assertAlmostEqual(metrics["selection_score"], 0.8 * 0.5 + 0.2 * 2 / 3)

    def test_promoted_initial_symptom_is_excluded_from_inquiry_recall(self):
        metrics = prediction_metrics([
            {"pred_disease": "a", "target_disease": "a", "explicit_symptoms": {},
             "implicit_symptoms": {"initial": True, "asked": False},
             "inquiry_symptom": ["asked"]},
        ])
        self.assertEqual(metrics["available_implicit_symptoms"], 1)
        self.assertEqual(metrics["symptom_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
