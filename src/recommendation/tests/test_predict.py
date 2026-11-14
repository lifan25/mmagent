import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from src.recommendation.model import SSPNetAdapter
from src.recommendation.predict import SSPNetRecommender, get_default_recommender, recommend


class PredictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name)
        cls.vocabulary = {"diagnoses": ["<UNK>", "SNOMED-CT|100001", "SNOMED-CT|100002"],
                          "procedures": ["<UNK>", "SNOMED-CT|200001"],
                          "medications": ["A10A", "N02B", "R03A"]}
        cls.graph = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=np.float32)
        np.savez(cls.path / "graphs.npz", ehr=cls.graph, ddi=cls.graph)
        (cls.path / "vocabulary.json").write_text(json.dumps(cls.vocabulary), encoding="utf-8")
        (cls.path / "mapping-decisions.json").write_text(json.dumps({
            "100": {"classes": ["A10A"]}, "200": {"classes": ["A10A", "N02B"]},
            "300": {"classes": ["C01D"]}}), encoding="utf-8")
        (cls.path / "manifest.json").write_text('{"source_a1":"synthetic_fixture"}', encoding="utf-8")
        config = {"dim": 16, "initial_inter": .1, "initial_garm": .1,
                  "threshold": .5, "prepared_dir": str(cls.path)}
        model = SSPNetAdapter(config, (3, 2, 3), cls.graph, cls.graph, torch.device("cpu"))
        torch.save({"state_dict": model.state_dict(), "config": config,
                    "vocabulary": cls.vocabulary, "epoch": 0}, cls.path / "best.pt")
        cls.predictor = SSPNetRecommender(cls.path / "best.pt", cls.path)
        cls.fixture = {"contract_version": "0.1-draft", "data_kind": "synthetic", "case_id": "fictional-test",
                       "diagnoses": [{"system": "SNOMED-CT", "code": "100002"}], "procedures": [],
                       "context": {"allergies": None},
                       "history": [{"visit_index": 1, "diagnoses": [{"system": "SNOMED-CT", "code": "100001"}],
                                    "procedures": [], "medications": [{"system": "RxNorm", "code": "100"}]}]}

    @classmethod
    def tearDownClass(cls):
        get_default_recommender.cache_clear()
        cls.temp.cleanup()

    def setUp(self):
        self.case = copy.deepcopy(self.fixture)

    def test_empty_procedures_mapping_scores_and_no_input_mutation(self):
        self.case["history"][0]["medications"].append({"system": "ATC3", "code": "A10A"})
        self.case["diagnoses"] += [self.case["diagnoses"][0], {"system": "SNOMED-CT", "code": "100001"}]
        original = copy.deepcopy(self.case)
        with patch.object(self.predictor.model, "forward", wraps=self.predictor.model.forward) as forward:
            result = self.predictor.score_case(self.case)
            self.assertEqual(forward.call_count, 1)
        self.assertEqual(self.case, original)
        self.assertEqual(result["encoded_input"], [[[1], [], [0]], [[1, 2], [], []]])
        self.assertEqual(result["recommendation"]["status"], "ok")
        self.assertEqual(len(result["full_scores"]), 3)
        self.assertTrue(all(0 <= score <= 1 for score in result["full_scores"]))
        self.assertEqual([x["drug"]["code"] for x in result["recommendation"]["candidates"]],
                         [c for c, s in zip(result["medication_codes"], result["full_scores"]) if s >= .5])
        json.dumps(self.predictor.manifest)

    def test_null_empty_and_missing_history_do_not_infer(self):
        variants = [("procedures", None, "needs_information"), ("history", None, "needs_information"),
                    ("history", [], "unsupported_input"), ("diagnoses", [], "needs_information")]
        with patch.object(self.predictor.model, "forward") as forward:
            for field, value, expected in variants:
                case = copy.deepcopy(self.fixture); case[field] = value
                result = self.predictor.score_case(case)
                self.assertEqual(result["recommendation"]["status"], expected)
                self.assertEqual(result["recommendation"]["candidates"], [])
                self.assertIsNone(result["full_scores"])
            case = copy.deepcopy(self.fixture); case["history"][0]["medications"] = []
            self.assertEqual(self.predictor.recommend(case)["status"], "unsupported_input")
            forward.assert_not_called()

    def test_unknown_and_ambiguous_codes_reject_entire_case(self):
        with patch.object(self.predictor.model, "forward") as forward:
            for field, code in [("diagnoses", "999999"), ("procedures", "999999")]:
                case = copy.deepcopy(self.fixture); case[field] = [{"system": "SNOMED-CT", "code": code}]
                output = self.predictor.recommend(case)
                self.assertEqual(output["status"], "unsupported_input")
                self.assertIn("unsupported_code", [i["code"] for i in output["input_issues"]])
            for system, code in [("RxNorm", "200"), ("RxNorm", "300"), ("RxNorm", "404"), ("ATC", "A10A")]:
                case = copy.deepcopy(self.fixture)
                case["history"][0]["medications"].append({"system": system, "code": code})
                output = self.predictor.recommend(case)
                self.assertEqual(output["status"], "unsupported_input")
                self.assertEqual(output["candidates"], [])
            forward.assert_not_called()

    def test_current_medication_answers_are_rejected(self):
        with patch.object(self.predictor.model, "forward") as forward:
            for field in ("medications", "target_medications", "target"):
                case = copy.deepcopy(self.fixture); case[field] = ["answer"]
                output = self.predictor.recommend(case)
                self.assertEqual(output["status"], "unsupported_input")
                self.assertIn("current_target_present", [i["code"] for i in output["input_issues"]])
            forward.assert_not_called()

    def test_bad_types_version_and_visit_order(self):
        cases = [None, {**self.case, "contract_version": "1.0"}, {**self.case, "procedures": "[]"}]
        for index in (-1, True, "1"):
            case = copy.deepcopy(self.fixture); case["history"][0]["visit_index"] = index; cases.append(case)
        case = copy.deepcopy(self.fixture); case["history"].append(copy.deepcopy(case["history"][0])); cases.append(case)
        case = copy.deepcopy(self.fixture); case["diagnoses"][0]["code"] = 100001; cases.append(case)
        with patch.object(self.predictor.model, "forward") as forward:
            for case in cases:
                self.assertEqual(self.predictor.recommend(case)["status"], "unsupported_input")
            forward.assert_not_called()

    def test_context_does_not_change_sspnet_input(self):
        encoded = self.predictor._encode_case(self.case)[0]
        self.case["context"] = {"renal_status": "unknown", "allergies": []}
        self.assertEqual(encoded, self.predictor._encode_case(self.case)[0])

    def test_model_is_cached_but_cases_are_inferred_each_time(self):
        get_default_recommender.cache_clear()
        try:
            with patch("src.recommendation.predict.SSPNetRecommender", return_value=self.predictor) as constructor:
                with patch.object(self.predictor.model, "forward", wraps=self.predictor.model.forward) as forward:
                    recommend(self.case); recommend(self.case)
                    constructor.assert_called_once()
                    self.assertEqual(forward.call_count, 2)
        finally:
            get_default_recommender.cache_clear()

    def test_nonfinite_output_is_not_a_recommendation(self):
        with patch.object(self.predictor.model, "forward", return_value=(torch.full((1, 3), float("nan")), torch.tensor(0.))):
            output = self.predictor.score_case(self.case)
        self.assertEqual(output["recommendation"]["status"], "error")
        self.assertEqual(output["recommendation"]["candidates"], [])
        self.assertIsNone(output["full_scores"])

    def test_original_rxnorm_product_space_does_not_apply_atc_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            checkpoint = torch.load(self.path / "best.pt", weights_only=True)
            checkpoint["config"].update(medication_space="RxNorm", prepared_dir=str(path))
            checkpoint["vocabulary"]["medications"] = ["100", "200", "300"]
            torch.save(checkpoint, path / "best.pt")
            (path / "vocabulary.json").write_text(json.dumps(checkpoint["vocabulary"]), encoding="utf-8")
            (path / "mapping-decisions.json").write_text("{}", encoding="utf-8")
            (path / "manifest.json").write_text('{"medication_space":"RxNorm"}', encoding="utf-8")
            (path / "drug-catalog.json").write_text(json.dumps({code: {"code": code, "system": "RxNorm"}
                for code in ["100", "200", "300"]}), encoding="utf-8")
            np.savez(path / "graphs.npz", ehr=self.graph, ddi=self.graph)
            predictor = SSPNetRecommender(path / "best.pt")
            result = predictor.score_case(self.case)
            self.assertEqual(result["recommendation"]["status"], "ok")
            self.assertEqual(result["encoded_input"][0][2], [0])
            self.assertEqual(result["medication_codes"], ["100", "200", "300"])
            self.assertTrue(all(x["drug"]["system"] == "RxNorm" for x in result["recommendation"]["candidates"]))
            self.assertEqual(predictor.manifest["drug_system"], "RxNorm")
            for item in ({"system": "ATC3", "code": "A10A"}, {"system": "RxNorm", "code": "999"}):
                case = copy.deepcopy(self.case); case["history"][0]["medications"] = [item]
                self.assertEqual(predictor.recommend(case)["status"], "unsupported_input")

    def test_checkpoint_rejects_reordered_vocabulary_and_changed_ddi(self):
        path = self.path / "vocabulary.json"
        changed = copy.deepcopy(self.vocabulary); changed["medications"].reverse()
        try:
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "vocabulary"):
                SSPNetRecommender(self.path / "best.pt", self.path)
        finally:
            path.write_text(json.dumps(self.vocabulary), encoding="utf-8")
        try:
            np.savez(self.path / "graphs.npz", ehr=self.graph, ddi=np.zeros_like(self.graph))
            with self.assertRaisesRegex(ValueError, "DDI graph differs"):
                SSPNetRecommender(self.path / "best.pt", self.path)
        finally:
            np.savez(self.path / "graphs.npz", ehr=self.graph, ddi=self.graph)


if __name__ == "__main__":
    unittest.main()
