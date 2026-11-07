import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.data_evaluation.cohort import normalize, prediction_examples, select_and_split, prepare_dataset


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
    def test_empty_procedures_are_retained_and_marked_without_invented_codes(self):
        data = visits()
        for v in data:
            v['procedures'] = []
        selected, _, summary = select_and_split(data, 8, [4,1,1], 2, False)
        self.assertEqual(len(selected), len(data))
        self.assertEqual(summary['selected_empty_procedure_visits'], len(data))
        examples = list(prediction_examples(selected))
        self.assertEqual(examples[1]['case']['procedures'], [])
        self.assertEqual(examples[1]['case']['context']['procedure_record_status'], 'not_recorded')
        self.assertEqual(examples[1]['case']['history'][0]['procedures'], [])
        self.assertEqual(examples[1]['target_medications'], selected[1]['medications'])
        with self.assertRaises(ValueError):
            select_and_split(data, 8, [4,1,1], 2, True)

    def test_export_preserves_all_linked_visits_separate_from_main_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables = {
                'patients': (['Id'], [[p] for p in ['a', 'b', 'c', 'single']]),
                'encounters': (['Id','PATIENT','START','STOP'], []),
                'conditions': (['PATIENT','ENCOUNTER','CODE'], []),
                'procedures': (['PATIENT','ENCOUNTER','CODE'], []),
                'medications': (['PATIENT','ENCOUNTER','CODE','START'], []),
            }
            for patient in ['a', 'b', 'c', 'single']:
                for i in range(1 if patient == 'single' else 2):
                    key = f'{patient}-{i}'
                    start, stop = f'2020-01-{i*3+1:02}', f'2020-01-{i*3+2:02}'
                    tables['encounters'][1].append([key,patient,start,stop])
                    for name in ['conditions','procedures']:
                        tables[name][1].append([patient,key,'001'])
                    tables['medications'][1].append([patient,key,'0001',start])
            for name, (header, rows) in tables.items():
                with (root/f'{name}.csv').open('w', newline='', encoding='utf-8') as f:
                    writer=csv.writer(f); writer.writerow(header); writer.writerows(rows)
            config={'seed':8,'split_weights':[4,1,1],'min_visits':2,'require_procedures':True,
                    'datasets':{'synthea':{'input_dir':'.','output_dir':'out','dataset':'toy','source':'fictional test'}}}
            summary=prepare_dataset(root,config,'synthea')
            def load(name):
                return [json.loads(line) for line in (root/'out'/name).read_text().splitlines()]
            self.assertEqual(len(load('visits.jsonl')),7)
            self.assertEqual(len(load('main_visits.jsonl')),6)
            self.assertTrue(any(v['patient_id']=='single' for v in load('visits.jsonl')))
            self.assertEqual(len(load('main_prediction_examples.jsonl')),3)
            self.assertEqual(summary['main_prediction_examples'],3)
            self.assertEqual(sum(x['examples'] for x in summary['main_prediction_counts'].values()),3)
            with self.assertRaisesRegex(ValueError,'already contains'):
                prepare_dataset(root,config,'synthea')

    def test_two_visit_cohort_keeps_pairs_and_singletons_remain_in_source(self):
        data = [v for v in visits(12) if v['visit_index'] <= 2]
        singleton = copy.deepcopy(data[0])
        singleton.update(patient_id='single', visit_id='single-1')
        data.append(singleton)
        selected, split, stats = select_and_split(data, 8, [4, 1, 1], 2, True)
        self.assertEqual(len(data), 25)
        self.assertEqual(len(selected), 24)
        self.assertEqual(stats['selected_patients'], 12)
        self.assertFalse(any('single' in ids for ids in split.values()))
        examples = list(prediction_examples(selected))
        self.assertEqual(sum(bool(e['case']['history']) for e in examples), 12)
        one_visit_stats = select_and_split(data, 8, [4, 1, 1], 1, True)[2]
        self.assertEqual(one_visit_stats['patients_with_at_least_three_visits'], 0)

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
