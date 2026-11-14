import unittest

from src.data_evaluation.evaluate_checks import ROOT, reference_state, replay, summarize_reference
from src.data_evaluation.prepare_context import VERSION
from src.knowledge.check import load_product_metadata, load_rules


class CheckEvaluationTests(unittest.TestCase):
    def test_replay_uses_saved_candidates_and_reports_rejected_input(self):
        case = {"case_id": "fictional", "data_kind": "synthetic", "contract_version": "0.1-draft", "context": {}}
        rec = {"case_id": "fictional", "data_kind": "synthetic", "contract_version": "0.1-draft",
               "status": "ok", "execution": "model_inference",
               "candidates": [{"drug": {"system": "RxNorm", "code": "860975"}, "score": 0.7}]}
        cases = {"fictional": case, "rejected": {**case, "case_id": "rejected"}}
        saved = {"fictional": {"agent": {"recommendation": rec}},
                 "rejected": {"agent": {"recommendation": {**rec, "status": "unsupported_input", "candidates": []}}}}
        context = {"version": VERSION, "cases": {"fictional": {"egfr_ml_min_1_73m2": 28}}}
        rows, summary = replay(cases, saved, context,
            load_rules(ROOT / "src/knowledge/rules/medication-llm-rxnorm-scope-v1.json"), load_product_metadata())
        self.assertEqual(summary["supported_cases"], 1)
        self.assertEqual(summary["rejected_inputs"], 1)
        self.assertEqual(summary["flagged_cases"], 1)
        self.assertEqual(summary["any_check_case_coverage_all_inputs"], .5)
        self.assertEqual(rec["candidates"][0]["score"], .7)
        self.assertIsNone(rows[1]["check_report"])

    def test_unknown_is_not_clear_and_pair_count_is_independent(self):
        report = {"findings": [], "missing_fields": [], "coverage": {"checked_rule_count": 0, "pending_rule_count": 0}}
        self.assertEqual(reference_state(report), "not_applicable")
        self.assertEqual(reference_state({**report, "missing_fields": ["identity"]}), "unknown")
        self.assertEqual(reference_state({**report, "pair_coverage": {"pending_pair_count": 1}}), "unknown")
        self.assertEqual(reference_state({**report, "findings": [{"candidate_indices": [0, 1]}]}), "flag")
        self.assertEqual(reference_state({**report, "coverage": {"checked_rule_count": 1, "pending_rule_count": 0}}), "clear_within_rule")

    def test_reference_errors_keep_denominator_and_undefined_strata_are_null(self):
        rows = [{"family": "F", "expected": "unknown", "actual": "clear_within_rule"},
                {"family": "F", "expected": "flag", "actual": "unknown"},
                {"family": "G", "expected": "flag", "actual": "flag"}]
        report = summarize_reference(rows)
        self.assertEqual(report["agreement_rate"], 1/3)
        self.assertEqual(report["unknown_misreported_clear"], 1)
        self.assertEqual(report["missed_reference_flags"], 1)
        self.assertIsNone(report["by_expected_state"]["not_applicable"]["agreement_rate"])


if __name__ == "__main__":
    unittest.main()
