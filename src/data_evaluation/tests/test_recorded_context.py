import copy
import unittest

from src.data_evaluation.prepare_context import recorded_patient_facts


class RecordedContextTests(unittest.TestCase):
    def setUp(self):
        self.visit = {"patient_id": "fictional", "visit_id": "current",
                      "admitted_at": "2020-06-01T10:00:00Z", "discharged_at": "2020-06-01T11:00:00Z"}
        self.patient = {"Id": "fictional", "BIRTHDATE": "2000-06-02"}
        self.source = {"Id": "previous", "PATIENT": "fictional", "START": "2019-01-02T09:00:00Z",
                       "STOP": "2019-01-02T10:00:00Z"}
        self.row = {"PATIENT": "fictional", "ENCOUNTER": "previous", "CODE": "53741008",
                    "START": "2019-01-01", "STOP": ""}

    def fact(self, rows=None, source=None, patient=None):
        return recorded_patient_facts(self.visit, patient or self.patient, [self.row] if rows is None else rows,
                                       {"previous": source or self.source})

    def test_recorded_disease_available_only_after_source_encounter_and_no_false_from_absence(self):
        facts, evidence, _ = self.fact()
        self.assertEqual(facts["age_years"], 19)
        self.assertIs(facts["coronary_artery_disease"], True)
        self.assertEqual(evidence[-1]["source_encounter_ended_at"], self.source["STOP"])
        self.assertIsNone(self.fact(rows=[])[0]["coronary_artery_disease"])
        later = {**self.source, "START": "2020-06-02T09:00:00Z", "STOP": "2020-06-02T10:00:00Z"}
        self.assertIsNone(self.fact(source=later)[0]["coronary_artery_disease"])

    def test_overlap_and_resolution_on_cutoff_day_are_not_promoted_to_known(self):
        overlapping = {**self.source, "STOP": "2020-06-01T10:30:00Z"}
        self.assertIsNone(self.fact(source=overlapping)[0]["coronary_artery_disease"])
        for stop in ("2020-05-31", "2020-06-01", "2018-01-01", "invalid"):
            self.assertIsNone(self.fact(rows=[{**self.row, "STOP": stop}])[0]["coronary_artery_disease"])

    def test_later_resolution_censored_and_original_rows_preserved(self):
        original = copy.deepcopy(self.row)
        without_stop = self.fact()[0]
        future_row = {**self.row, "STOP": "2021-01-01"}
        facts, evidence, _ = self.fact(rows=[future_row])
        self.assertEqual(facts, without_stop)
        self.assertNotIn("2021-01-01", str(evidence))
        self.assertEqual(self.row, original)

    def test_patient_mismatch_and_invalid_birth_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            self.fact(source={**self.source, "PATIENT": "someone-else"})
        for birth in ("", "bad", "2030-01-01"):
            self.assertIsNone(self.fact(patient={**self.patient, "BIRTHDATE": birth})[0]["age_years"])

    def test_same_encounter_diagnosis_supported_but_future_diagnosis_not(self):
        source = {"current": {"Id": "current", "PATIENT": "fictional", "START": self.visit["admitted_at"],
                               "STOP": self.visit["discharged_at"]}}
        row = {**self.row, "ENCOUNTER": "current", "START": "2020-06-01"}
        result = recorded_patient_facts(self.visit, self.patient, [row], source)
        self.assertIs(result[0]["coronary_artery_disease"], True)
        result = recorded_patient_facts(self.visit, self.patient, [{**row, "START": "2020-06-02"}], source)
        self.assertIsNone(result[0]["coronary_artery_disease"])


if __name__ == "__main__":
    unittest.main()
