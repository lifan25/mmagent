import copy
import unittest

from src.data_evaluation.pipeline import MedicationAgent


def case():
    return {"contract_version": "0.1-draft", "data_kind": "synthetic", "case_id": "fictional-1",
            "diagnoses": [], "procedures": [], "history": [], "context": {"renal_status": None}}


class Recommender:
    def __init__(self, status="ok"):
        self.calls = 0
        self.status = status

    def score_case(self, value):
        self.calls += 1
        self.received = copy.deepcopy(value)
        rec = {k: value[k] for k in ("contract_version", "data_kind", "case_id")}
        rec.update(status=self.status, input_issues=[], model_version="fictional-unit-test",
                   execution="synthetic_fixture", candidates=[{"drug": {"system": "toy", "code": "M1"}, "score": .8}]
                   if self.status == "ok" else [])
        return {"recommendation": rec, "full_scores": [.8] if self.status == "ok" else None}


def checker(state):
    def run(value, rec, rules):
        report = {k: value[k] for k in ("contract_version", "data_kind", "case_id")}
        report.update(status=state, applied_rules=[], missing_fields=["renal_status"],
                      findings=[], unchecked_reasons=[], coverage={})
        return report
    return run


class PipelineTests(unittest.TestCase):
    def test_each_check_state_routes_without_rewriting_candidates(self):
        for state, expected in [("checked", "completed"), ("issues_found", "review_required"),
                                ("insufficient_information", "needs_information"), ("not_checked", "not_checked")]:
            model = Recommender()
            result, scores = MedicationAgent(model, rules=[], checker=checker(state)).run_with_scores(case())
            self.assertEqual(result["status"], expected)
            self.assertEqual(model.calls, 1)
            self.assertEqual(result["recommendation"]["candidates"], scores["recommendation"]["candidates"])
            self.assertNotIn("full_scores", result)

    def test_rejected_recommendation_never_reaches_checker(self):
        def fail(*args):
            self.fail("Checker must not run on unsupported candidates")
        result = MedicationAgent(Recommender("unsupported_input"), rules=[], checker=fail).run(case())
        self.assertIsNone(result["check_report"])
        self.assertEqual(result["trace"][-1]["status"], "skipped")

    def test_answer_fields_and_contract_mismatch_stop_before_model(self):
        model = Recommender()
        agent = MedicationAgent(model, rules=[], checker=checker("checked"))
        for patch in ({"target_medications": []}, {"medications": []}, {"contract_version": "other"}):
            with self.assertRaises(ValueError):
                agent.run({**case(), **patch})
        self.assertEqual(model.calls, 0)

    def test_unknown_extra_metadata_is_not_forwarded_and_wrong_identity_is_rejected(self):
        model = Recommender()
        def wrong(value, rec, rules):
            result = checker("checked")(value, rec, rules)
            result["case_id"] = "another-case"
            return result
        with self.assertRaises(ValueError):
            MedicationAgent(model, rules=[], checker=wrong).run({**case(), "untrusted_extra": "ignore"})
        self.assertNotIn("untrusted_extra", model.received)

    def test_flag_only_checker_cannot_delete_candidates(self):
        def mutating(value, rec, rules):
            rec["candidates"].clear()
            return checker("checked")(value, rec, rules)
        with self.assertRaisesRegex(ValueError, "must not alter"):
            MedicationAgent(Recommender(), rules=[], checker=mutating).run(case())


if __name__ == "__main__":
    unittest.main()
