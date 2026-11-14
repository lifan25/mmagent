import copy
import tempfile
import unittest
from pathlib import Path

from src.data_evaluation.prepare_medpic import (
    annotation_record, check_annotations, digest, dump, payload, save_new,
    select_development,
)


class MedpicPreparationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{
            "instance_id": f"fictional-{n}", "question": f"Fictional question {n % 4}?",
            "patient_vignette": "Fictional fixture: age 70; renal function not reported.",
            "options": {"A": "Example drug", "B": "None of the above"},
            "answer": ["A"], "taxonomy_reasoning_operation": "secret-label",
        } for n in range(30)]

    def test_labels_cannot_change_selection_or_input(self):
        original = select_development(self.rows)
        changed = copy.deepcopy(self.rows)
        for row in changed:
            row["answer"] = ["B"]
            row["taxonomy_reasoning_operation"] = "other-secret"
        selected = select_development(changed)
        self.assertEqual([p for p, _ in original], [p for p, _ in selected])
        self.assertEqual([payload(r) for _, r in original], [payload(r) for _, r in selected])
        self.assertEqual(set(payload(self.rows[0])), {"patient_vignette", "question", "options"})
        self.assertEqual(len(original), 20)

    def test_repeated_question_ties_preserve_source_order(self):
        selected = select_development(self.rows, len(self.rows))
        for question in {r["question"] for r in self.rows}:
            positions = [p for p, r in selected if r["question"] == question]
            self.assertEqual(positions, sorted(positions))

    def setup_pack(self, folder):
        case = {"case_key": "fictional-key", "input": payload(self.rows[0])}
        text = dump([case])
        (folder / "inputs.development.json").write_text(text, encoding="utf-8", newline="\n")
        (folder / "manifest.json").write_text(dump({"inputs_sha256": digest(text.encode("utf-8"))}), encoding="utf-8")
        pack = {"reviewer": None, "reviewer_kind": None, "records": [annotation_record(case)]}
        return pack

    def test_pending_is_not_human_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pack = self.setup_pack(folder)
            path = folder / "annotations.json"
            path.write_text(dump(pack), encoding="utf-8")
            result = check_annotations(path, folder)
            self.assertEqual(result["status_counts"], {"pending": 1})
            self.assertFalse(result["clinical_correctness_validated"])
            self.assertIsNone(result["reviewer_kind"])

    def test_missing_option_or_wrong_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pack = self.setup_pack(folder)
            path = folder / "annotations.json"
            for broken in ("missing_option", "made_up_quote", "wrong_offset"):
                edited = copy.deepcopy(pack)
                if broken == "missing_option":
                    edited["records"][0]["candidates"].pop()
                else:
                    edited["records"][0]["facts"] = [{"evidence": [{
                        "field": "patient_vignette", "quote": "normal" if broken == "made_up_quote" else "age 70",
                        "start": 0, "end": 6,
                    }]}]
                path.write_text(dump(edited), encoding="utf-8")
                with self.assertRaises(ValueError):
                    check_annotations(path, folder)

    def test_refuses_overwriting_review_and_changed_frozen_input(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pack = self.setup_pack(folder)
            path = folder / "annotations.json"
            save_new({path: dump(pack)})
            save_new({path: dump(pack)})
            with self.assertRaises(ValueError):
                save_new({path: "changed"})
            with (folder / "inputs.development.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaises(ValueError):
                check_annotations(path, folder)

    def test_complete_cannot_hide_unreviewed_mapping_or_invent_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pack = self.setup_pack(folder)
            pack.update(reviewer="Fictional test reviewer", reviewer_kind="ai_draft")
            record = pack["records"][0]
            record["review_status"] = "complete"
            record["eligibility"] = {"decision": "in_scope", "action": "avoid", "reason": "Fictional test only"}
            for candidate in record["candidates"]:
                candidate["entity_type"] = "drug"
            path = folder / "annotations.json"
            path.write_text(dump(pack), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mapping states"):
                check_annotations(path, folder)
            for candidate in record["candidates"]:
                candidate["mapping_status"] = "unresolved"
            record["facts"] = [{"field": "allergy", "raw_value": None, "raw_unit": None,
                                "value": False, "unit": None, "status": "not_reported",
                                "time": None, "evidence": []}]
            path.write_text(dump(pack), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "remain null"):
                check_annotations(path, folder)
            record["facts"][0]["value"] = None
            text = self.rows[0]["patient_vignette"]
            start = text.index("age 70")
            record["facts"].append({
                "field": "age", "raw_value": 70, "raw_unit": "years", "value": 70,
                "unit": "years", "status": "explicit_positive", "time": "current",
                "evidence": [{"field": "patient_vignette", "quote": "age 70", "start": start, "end": start + 6}],
            })
            path.write_text(dump(pack), encoding="utf-8")
            result = check_annotations(path, folder)
            self.assertEqual(result["status_counts"], {"complete": 1})
            self.assertEqual(result["reviewer_kind"], "ai_draft")
            self.assertFalse(result["clinical_correctness_validated"])


if __name__ == "__main__":
    unittest.main()
