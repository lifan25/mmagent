import unittest

from src.knowledge.run_local_pilot import model_input


class LocalPilotTests(unittest.TestCase):
    def test_list_answer_and_identity_are_not_sent(self):
        row = {f"drug{i}": f"fictional_{i}" for i in range(1, 7)}
        row.update(case_id="example", doses="fictional doses", DDI="answer", Classification="label")
        payload = model_input(row, "lists")
        self.assertEqual(set(payload), {*(f"drug{i}" for i in range(1, 7)), "doses"})

    def test_corpus_labels_are_not_sent(self):
        row = {"case_id": "example", "target": "interaction", "input": {"sentence": "A and B",
               "entity1": {"text": "A", "charOffset": "0-0", "label": "leak"},
               "entity2": {"text": "B", "charOffset": "6-6"}, "ddi": True}}
        payload = model_input(row, "corpus")
        self.assertEqual(set(payload), {"sentence", "entity1", "entity2"})
        self.assertNotIn("label", payload["entity1"])


if __name__ == "__main__":
    unittest.main()
