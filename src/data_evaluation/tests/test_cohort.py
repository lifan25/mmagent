import copy
import csv
import tempfile
import unittest
from pathlib import Path

from src.data_evaluation.cohort import normalize, prediction_examples, select_and_split


def visits(n=12):
    result = []
    for p in range(n):
        for i in range(3):
            result.append({"dataset": "toy", "data_kind": "synthetic", "patient_id": str(p),
                           "visit_id": f"{p}-{i}", "visit_index": i+1,
                           "admitted_at": f"2020-01-{i*3+1:02}T00:00:00Z",
                           "discharged_at": f"2020-01-{i*3+2:02}T00:00:00Z",
                           "diagnoses": [{"system": "toy", "code": "D"}],
                           "procedures": [{"system": "toy", "code": "P"}],
                           "medications": [{"system": "RxNorm", "code": f"00{i}"}],
                           "medication_records": [{"code": f"00{i}", "start": f"2020-01-{i*3+1:02}T00:00:00Z"}],
                           "time_issues": []})
    return result


class CohortTests(unittest.TestCase):
    def test_repeatable_disjoint_split_independent_of_input_order(self):
        data = visits()
        a, split, _ = select_and_split(data, 8, [4, 1, 1], 3, True)
        _, again, _ = select_and_split(list(reversed(data)), 8, [4, 1, 1], 3, True)
        self.assertEqual(split, again)
        groups = [set(ids) for ids in split.values()]
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
        self.assertEqual(sum(map(len, groups)), 12)
        self.assertEqual(len(a), 36)

    def test_tiny_split_is_explicit_and_insufficient_patients_fail(self):
        _, split, stats = select_and_split(visits(3), 8, [4, 1, 1], 3, True)
        self.assertEqual([len(v) for v in split.values()], [1, 1, 1])
        self.assertTrue(stats['small_sample_split_adjustment'])
        with self.assertRaises(ValueError):
            select_and_split(visits(2), 8, [4, 1, 1], 3, True)

    def test_filter_counts_and_no_input_mutation(self):
        data = visits()
        data[0]['procedures'] = []
        before = copy.deepcopy(data)
        selected, _, stats = select_and_split(data, 8, [4, 1, 1], 3, True)
        self.assertEqual(data, before)
        self.assertEqual(stats['excluded_visits_by_record_filter'], 1)
        self.assertEqual(stats['excluded_visits_by_patient_filter'], 2)
        self.assertEqual(len(selected), len(data)-3)

    def test_history_excludes_overlap_future_medication_and_current_target(self):
        selected, _, _ = select_and_split(visits(), 8, [4, 1, 1], 3, True)
        first = selected[0]
        first['medication_records'].append({'code': 'FUTURE', 'start': '2030-01-01'})
        records = list(prediction_examples(selected))
        self.assertIsNone(records[0]['case']['history'])
        second = records[1]
        self.assertNotIn('medications', second['case'])
        self.assertEqual(second['target_medications'], selected[1]['medications'])
        self.assertEqual(second['case']['history'][0]['medications'], first['medications'])
        first['discharged_at'] = selected[1]['admitted_at']
        self.assertIsNone(list(prediction_examples(selected))[1]['case']['history'])

    def test_normalize_csv_orphans_duplicates_missing_and_code_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tables = {
                'patients': (['Id'], [['p']]),
                'encounters': (['Id','PATIENT','START','STOP'], [['v','p','2020-01-01','2020-01-02'], ['w','p','bad','']]),
                'conditions': (['PATIENT','ENCOUNTER','CODE'], [['p','v','001'], ['p','v','001'], ['p','missing','002']]),
                'procedures': (['PATIENT','ENCOUNTER','CODE'], []),
                'medications': (['PATIENT','ENCOUNTER','CODE','START'], [['p','v','000123','2020-01-01'], ['p','v','0','2020-01-01']]),
            }
            for name, (header, rows) in tables.items():
                with (base/f'{name}.csv').open('w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f); writer.writerow(header); writer.writerows(rows)
            result, stats = normalize(base, 'synthea', 'toy')
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]['diagnoses'], [{'system':'SNOMED-CT','code':'001'}])
            self.assertEqual(result[0]['record_counts']['diagnoses'], 2)
            self.assertEqual(result[0]['medications'][0]['code'], '000123')
            self.assertEqual(result[0]['invalid_medication_code_rows'], 1)
            self.assertEqual(len(result[0]['medication_records']), 2)
            self.assertEqual(stats['audit']['conditions:orphan_rows'], 1)
            self.assertIn('invalid_start', result[1]['time_issues'])
            self.assertEqual(result[0]['procedures'], [])
            # A known encounter must never absorb another patient's detail row.
            with (base/'conditions.csv').open('a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(['other', 'v', '003'])
            with self.assertRaisesRegex(ValueError, 'patient mismatch'):
                normalize(base, 'synthea', 'toy')


if __name__ == '__main__':
    unittest.main()
