"""Fine-product labels, preserved unknown targets and honest score availability."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from src.recommendation.prepare import prepare
from src.recommendation.rxnorm import ddi_graph, product_catalog
from src.recommendation.train import evaluate, metrics


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(codes):
    return {"schema_version": "rxnorm-products-v1", "version": {"version": "fictional-test"},
            "drugs": {code: {"rxcuiStatusHistory": {"attributes": {"rxcui": code, "name": "fictional",
                "tty": "SCD", "isMultipleIngredient": "NO"}, "metaData": {"status": "Active"},
                "definitionalFeatures": {}}} for code in codes}}


class RxNormTests(unittest.TestCase):
    def test_unknown_target_counts_as_missed_and_only_complete_targets_have_ap(self):
        rows = [
            {"patient_id": "p", "target": [0], "outside_train_target_codes": ["999"], "input_supported": True},
            {"patient_id": "p", "target": [], "outside_train_target_codes": ["888"], "input_supported": True},
            {"patient_id": "q", "target": [1], "outside_train_target_codes": [], "input_supported": False},
            {"patient_id": "r", "target": [1], "outside_train_target_codes": [], "input_supported": True},
        ]
        probabilities = np.array([[.8, .2], [.1, .9], [np.nan, np.nan], [.1, .9]])
        result = metrics(rows, probabilities, 2, np.zeros((2, 2)), .5, np.zeros((2, 2)))
        self.assertAlmostEqual(result["jaccard"], .375)
        self.assertAlmostEqual(result["f1"], (2 / 3 + 1) / 4)
        self.assertEqual(result["prauc_average_precision"], 1.)
        self.assertEqual(result["ap_evaluable_samples"], 1)
        self.assertEqual(result["ap_case_coverage"], .25)
        self.assertEqual(result["input_rejected_samples"], 1)
        self.assertEqual(result["outside_train_target_occurrences"], 2)
        no_ap = metrics(rows[:2], probabilities[:2], 2, np.zeros((2, 2)), .5)
        self.assertIsNone(no_ap["prauc_average_precision"])
        self.assertIsNone(no_ap["patient_macro"]["prauc_average_precision"])
        json.dumps(no_ap, allow_nan=False)

    def test_rejected_input_has_nan_scores_without_model_call(self):
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def forward(self, patient):
                self.calls += 1
                return torch.tensor([[1., -1.]]), torch.tensor(0.)

        rows = [{"patient_id": "p", "input": [[[1], [], []]], "target": [0],
                 "outside_train_target_codes": [], "input_supported": allowed,
                 "empty_current_procedures": True, "empty_history_procedures": True} for allowed in (True, False)]
        model = Model()
        report, scores = evaluate(model, rows, 2, np.zeros((2, 2)), .5)
        self.assertEqual(model.calls, 1)
        self.assertTrue(np.isfinite(scores[0]).all())
        self.assertTrue(np.isnan(scores[1]).all())
        self.assertEqual(report["overall"]["jaccard"], .5)
        self.assertEqual(report["overall"]["ap_evaluable_samples"], 1)

    def test_historical_identifier_is_not_silently_replaced(self):
        value = snapshot(["11"])
        history = value["drugs"]["11"]["rxcuiStatusHistory"]
        history["metaData"]["status"] = "Remapped"
        history["derivedConcepts"] = {"remappedConcept": [{"remappedRxCui": "12"}]}
        product = product_catalog(value, ["11"])["11"]
        self.assertEqual(product["code"], "11")
        self.assertEqual(product["status"], "Remapped")
        self.assertEqual(product["ingredient_and_strength"], [])

    def test_partial_mapping_never_enters_complete_pair_numerator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with (path / "drug-DDI.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["STITCH 1", "STITCH 2", "Polypharmacy Side Effect", "Side Effect Name"])
                writer.writerows([["CID1", "CID2", "event", "fictional"], ["CID1", "CID3", "event", "fictional"]])
            graph, mask, report = ddi_graph(path, {"11": 0, "12": 1, "13": 2}, 40,
                {"drug_cids": {"11": ["CID1"], "12": ["CID2"], "13": []},
                 "partial_drug_cids": {"11": ["CID1"], "12": ["CID2"], "13": ["CID3"]},
                 "mapping_complete": {"11": True, "12": True, "13": False}})
            np.testing.assert_array_equal(graph, [[0, 1, 0], [1, 0, 0], [0, 0, 0]])
            self.assertTrue(np.all(graph <= mask))
            self.assertEqual(report["partial_positive_edges_excluded"], 1)
            self.assertEqual(report["undirected_edges"], 1)

    def test_preparation_keeps_wholly_unseen_targets_and_unsupported_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            a1, reference, output = path / "a1", path / "reference", path / "prepared"
            a1.mkdir(); reference.mkdir()
            drug = lambda code: {"system": "RxNorm", "code": code}
            diagnosis = [{"system": "SNOMED-CT", "code": "100001"}]
            visits, examples = [], []
            for group, medicines in (("train", ["11", "12"]), ("validation", ["13"]), ("test", ["13"])):
                visits.append({"patient_id": group, "split": group, "diagnoses": diagnosis,
                               "procedures": [], "medications": [drug(x) for x in medicines]})
                case = {"case_id": group, "diagnoses": diagnosis, "procedures": [], "history": [
                    {"diagnoses": diagnosis, "procedures": [], "medications": [drug("13" if group == "test" else "11")]}]}
                examples.append({"patient_id": group, "split": group, "case": case,
                                 "target_medications": [drug("11" if group == "train" else "13")]})
            for name, rows in (("main_visits.jsonl", visits), ("main_prediction_examples.jsonl", examples)):
                (a1 / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            write_json(a1 / "split.json", {group: [group] for group in ("train", "validation", "test")})
            write_json(a1 / "manifest.json", {"data_kind": "synthetic_fixture"})
            write_json(path / "products.json", snapshot(["11", "12", "13"]))
            write_json(path / "bridge.json", {"drug_cids": {"11": ["CID1"], "12": ["CID2"]},
                                              "mapping_complete": {"11": True, "12": True}})
            (reference / "drug-DDI.csv").write_text("STITCH 1,STITCH 2,Polypharmacy Side Effect,Side Effect Name\nCID1,CID2,e,fictional\n")
            prepare({"a1_dir": str(a1), "reference_dir": str(reference), "prepared_dir": str(output),
                     "medication_space": "RxNorm", "rxnorm_snapshot": str(path / "products.json"),
                     "ddi_mapping_snapshot": str(path / "bridge.json"), "ddi_least_frequent_events": 40})
            validation = json.loads((output / "validation.jsonl").read_text())
            test = json.loads((output / "test.jsonl").read_text())
            self.assertEqual(validation["target"], [])
            self.assertEqual(validation["outside_train_target_codes"], ["13"])
            self.assertTrue(validation["input_supported"])
            self.assertFalse(test["input_supported"])
            self.assertEqual(test["outside_train_input_codes"][0]["code"], "13")
            self.assertEqual(test["input"][-1][2], [])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["train_history_only_labels"], ["12"])
            self.assertEqual(manifest["splits"]["test"]["retained_examples"], 1)


if __name__ == "__main__":
    unittest.main()
