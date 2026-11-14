"""用虚构记录检查关联，不把真实病例放进测试文件。"""

import unittest

from src.data_evaluation.prepare import organize_visits


def example():
    return {
        "PATIENTS": [{"subject_id": "1"}],
        "ADMISSIONS": [
            {"subject_id": "1", "hadm_id": "10", "admittime": "2020-02-01 00:00:00", "dischtime": ""},
            {"subject_id": "1", "hadm_id": "90", "admittime": "2020-01-01 00:00:00", "dischtime": ""},
        ],
        "DIAGNOSES_ICD": [
            {"subject_id": "1", "hadm_id": "90", "icd9_code": "001"},
            {"subject_id": "1", "hadm_id": "90", "icd9_code": "001"},
        ],
        "PROCEDURES_ICD": [],
        "PRESCRIPTIONS": [{"subject_id": "1", "hadm_id": "10", "ndc": "000123", "drug": "toy"}],
    }


class PrepareTests(unittest.TestCase):
    def test_time_order_grouping_missing_records_and_leading_zero(self):
        result = organize_visits(example(), "1")
        first, second = result["visits"]
        self.assertEqual([v["visit_id"] for v in result["visits"]], ["90", "10"])
        self.assertEqual(first["diagnosis_codes"], ["001"])
        self.assertEqual(first["record_counts"], {"diagnoses": 2, "procedures": 0, "prescriptions": 0})
        self.assertEqual(second["source_records"]["prescriptions"][0]["ndc"], "000123")
        self.assertEqual(second["diagnosis_codes"], [])

    def test_rejects_patient_mismatch(self):
        tables = example()
        tables["DIAGNOSES_ICD"][0]["subject_id"] = "2"
        with self.assertRaisesRegex(ValueError, "different patients"):
            organize_visits(tables, "1")

    def test_rejects_orphan_record(self):
        tables = example()
        tables["PRESCRIPTIONS"][0]["hadm_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unknown admission"):
            organize_visits(tables, "1")


if __name__ == "__main__":
    unittest.main()
