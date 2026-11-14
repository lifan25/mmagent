"""Mathematical and evidence-boundary checks, using only fictional fixtures."""

import itertools
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.special import softmax

from src.knowledge.bibm_diagnosis import positive_evidence
from src.knowledge.mln import ConditionalMLN


class ConditionalMLNTests(unittest.TestCase):
    def setUp(self):
        self.rules = [{"id": "fictional-a", "disease": "A", "symptoms": ["s", "t"], "source_id": "synthetic_fixture"},
                      {"id": "fictional-b", "disease": "B", "symptoms": ["t"], "source_id": "synthetic_fixture"}]
        self.model = ConditionalMLN(["A", "B", "C"], ["s", "t"], self.rules)
        self.model.weights = np.asarray([0.2, -0.3, 0.1, 1.4, -0.6])

    def test_matches_direct_possible_world_enumeration(self):
        for evidence in ([], ["s"], ["t"], ["s", "t"]):
            masses = np.zeros(3)
            for world in itertools.product((False, True), repeat=3):
                if sum(world) != 1:
                    continue
                counts = list(world)
                for rule in self.rules:
                    antecedent = all(s in evidence for s in rule["symptoms"])
                    consequent = world[self.model.diseases.index(rule["disease"])]
                    counts.append(not antecedent or consequent)
                masses[world.index(True)] = np.exp(np.dot(counts, self.model.weights))
            np.testing.assert_allclose(self.model.predict_proba([evidence])[0], masses / masses.sum(), atol=1e-14)
        # All implications are true under empty observations, and their equal
        # contributions cancel; hidden symptoms have not been asserted false.
        np.testing.assert_allclose(self.model.predict_proba([[]])[0], softmax(self.model.weights[:3]))

    def test_likelihood_gradient_and_fit(self):
        evidence, labels = [["s", "t"], ["s"], ["t"], []], ["A", "C", "B", "C"]
        counts = self.model.formula_counts(evidence)
        y = np.asarray([self.model.diseases.index(x) for x in labels])
        w = self.model.weights.copy()
        _, analytic = self.model.objective(w, counts, y, 0.01)
        numerical = []
        for i in range(len(w)):
            delta = np.eye(len(w))[i] * 1e-6
            plus = self.model.objective(w + delta, counts, y, 0.01)[0]
            minus = self.model.objective(w - delta, counts, y, 0.01)[0]
            numerical.append((plus - minus) / 2e-6)
        np.testing.assert_allclose(analytic, numerical, atol=1e-9)
        initial = self.model.objective(np.zeros_like(w), counts, y, 0.01)[0]
        self.model.fit(evidence, labels)
        self.assertTrue(self.model.fit_info["success"])
        self.assertLess(self.model.fit_info["objective"], initial)

    def test_labels_and_unasked_hidden_values_cannot_change_evidence(self):
        row = {"explicit_symptoms": {"s": True, "negative": False, "unknown": "UNK"},
               "implicit_symptoms": {"t": True, "unasked": True, "q": "UNK", "n": False},
               "inquiry_symptom": ["t", "q", "n", "not_recorded"], "target_disease": "A"}
        self.assertEqual(positive_evidence(row), ["s", "t"])
        row["target_disease"], row["implicit_symptoms"]["unasked"] = "B", False
        self.assertEqual(positive_evidence(row), ["s", "t"])
        self.assertEqual(positive_evidence(row, "explicit"), ["s"])
        row["explicit_symptoms"], row["inquiry_symptom"] = {}, []
        self.assertEqual(positive_evidence(row), [])  # No hidden bootstrap recreation.

    def test_roundtrip_and_label_free_test_database(self):
        self.rules[0]["rationale"] = "Unverified model narrative"
        self.assertNotIn("rationale", self.model.explain(["s", "t"])["active_rules"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.model.save(path / "model.json")
            restored = ConditionalMLN.load(path / "model.json")
            np.testing.assert_array_equal(restored.predict_proba([["s"]]), self.model.predict_proba([["s"]]))
            self.model.export_evidence(path / "test.db", [["s"]])
            self.assertNotIn("Diagnosis(", (path / "test.db").read_text())
            self.model.export_mln(path / "model.mln")
            self.assertIn("Diagnosis(disease!, patient)", (path / "model.mln").read_text())

    def test_invalid_rules_and_unknown_evidence_fail(self):
        with self.assertRaises(ValueError):
            ConditionalMLN(["A", "B"], ["s", "t"], self.rules + [self.rules[0]])
        with self.assertRaises(ValueError):
            self.model.predict_proba([["not_in_domain"]])
        prior = ConditionalMLN(["A", "B"], ["s"], []).fit([[], [], []], ["A", "A", "B"])
        self.assertGreater(prior.predict_proba([[]])[0, 0], 0.5)


if __name__ == "__main__":
    unittest.main()
