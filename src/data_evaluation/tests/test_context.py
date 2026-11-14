import copy
import unittest

from src.data_evaluation.prepare_context import VERSION, apply_context, encounter_fact, egfr_value


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.visit = {"patient_id": "fictional", "admitted_at": "2020-01-01T10:00:00Z",
                      "discharged_at": "2020-01-01T11:00:00Z"}
        self.row = {"PATIENT": "fictional", "CODE": "33914-3", "TYPE": "numeric",
                    "DATE": "2020-01-01T10:15:00Z", "VALUE": "28", "UNITS": "mL/min/{1.73_m2}",
                    "DESCRIPTION": "Estimated Glomerular Filtration Rate"}

    def test_exact_indexed_unit_and_documented_legacy_alias_only(self):
        self.assertEqual(egfr_value(self.row)[0], 28)
        self.assertIsNone(egfr_value({**self.row, "UNITS": "mL/min"})[0])
        self.assertEqual(egfr_value({**self.row, "UNITS": "mL/min", "DESCRIPTION": "GFR/1.73 sq M"})[0], 28)
        for value in ("nan", "inf", "-1", "unknown"):
            self.assertIsNone(egfr_value({**self.row, "VALUE": value})[0])
        self.assertIsNone(egfr_value({**self.row, "UNITS": "mg/dL"})[0])

    def test_latest_same_encounter_fact_not_future_or_history(self):
        rows = [self.row, {**self.row, "DATE": "2020-01-01T10:30:00Z", "VALUE": "40"},
                {**self.row, "DATE": "2020-01-01T11:01:00Z", "VALUE": "10"},
                {**self.row, "DATE": "2019-12-31T10:00:00Z", "VALUE": "10"}]
        original = copy.deepcopy(rows)
        fact, audit = encounter_fact(self.visit, rows, [])
        self.assertEqual(fact["egfr_ml_min_1_73m2"], 40)
        self.assertEqual(audit["egfr_outside_encounter_interval"], 2)
        self.assertIsNone(fact["perioperative_cabg"])
        self.assertEqual(rows, original)

    def test_conflicting_latest_unknown_and_patient_identity_checked(self):
        fact, audit = encounter_fact(self.visit, [self.row, {**self.row, "VALUE": "50"}], [])
        self.assertIsNone(fact["egfr_ml_min_1_73m2"])
        self.assertEqual(audit["conflicting_latest_egfr"], 1)
        with self.assertRaises(ValueError):
            encounter_fact(self.visit, [{**self.row, "PATIENT": "someone-else"}], [])

    def test_cabg_requires_current_record_and_never_infers_negative(self):
        procedure = {"PATIENT": "fictional", "CODE": "232717009", "DATE": "2020-01-01T10:15:00Z"}
        self.assertIs(encounter_fact(self.visit, [], [procedure])[0]["perioperative_cabg"], True)
        for records in ([], [{**procedure, "DATE": "2019-12-31T10:15:00Z"}], [{**procedure, "CODE": "other"}]):
            self.assertIsNone(encounter_fact(self.visit, [], records)[0]["perioperative_cabg"])

    def test_context_join_preserves_case_model_inputs_and_never_takes_target(self):
        case = {"case_id": "fictional", "context": {"task": "retrospective"},
                "diagnoses": [{"system": "toy", "code": "D"}], "procedures": [], "history": []}
        original = copy.deepcopy(case)
        snapshot = {"version": VERSION, "cases": {"fictional": {"egfr_ml_min_1_73m2": 28}}}
        updated = apply_context(case, snapshot)
        self.assertEqual(case, original)
        self.assertEqual(updated["diagnoses"], original["diagnoses"])
        self.assertEqual(updated["context"]["egfr_ml_min_1_73m2"], 28)
        with self.assertRaises(ValueError):
            apply_context(case, {**snapshot, "version": "other"})


if __name__ == "__main__":
    unittest.main()
