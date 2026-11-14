import copy
import unittest

from src.knowledge.check import DEFAULT_RULES, check, evaluate_condition, load_rules
from src.knowledge.extract import assess_candidate, compare_condition, output_schema, source_input, validate_condition


def fixture(drug=None, context=None):
    case = {"contract_version": "0.1-draft", "case_id": "fictional-medication-check",
            "data_kind": "synthetic", "context": context or {}}
    rec = {key: case[key] for key in ("contract_version", "case_id", "data_kind")}
    rec.update(status="ok", execution="synthetic_fixture", candidates=[{
        "drug": drug or {"system": "ATC5", "code": "A10BA02", "route": "oral", "dose_form": "tablet"},
        "score": 0.6}])
    return case, rec


class MedicationCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules()

    def test_metformin_threshold_and_invalid_measurements(self):
        for egfr, expected in [(29.9, "issues_found"), (30, "checked"), (45, "checked"),
                               (None, "insufficient_information"), (-1, "insufficient_information"),
                               (True, "insufficient_information"), (float("nan"), "insufficient_information")]:
            with self.subTest(egfr=egfr):
                case, rec = fixture(context={"egfr_ml_min_1_73m2": egfr})
                result = check(case, rec, self.rules)
                self.assertEqual(result["status"], expected)

    def test_numeric_domain_is_fixed_even_if_model_omits_minimum(self):
        condition = {"field": "egfr_ml_min_1_73m2", "op": "lt", "value": 30}
        for value in (-1, float("nan"), True, None):
            self.assertIsNone(evaluate_condition(condition, {"egfr_ml_min_1_73m2": value})[0])
        self.assertIs(evaluate_condition(condition, {"egfr_ml_min_1_73m2": 29.9})[0], True)
        self.assertIs(evaluate_condition(condition, {"egfr_ml_min_1_73m2": 30})[0], False)

    def test_cabg_is_known_present_absent_or_unknown(self):
        drug = {"system": "ATC5", "code": "M01AE01", "route": "oral", "dose_form": "tablet"}
        for cabg, status in [(True, "issues_found"), (False, "checked"), (None, "insufficient_information")]:
            self.assertEqual(check(*fixture(drug, {"perioperative_cabg": cabg}))["status"], status)

    def test_warfarin_exception_and_short_circuit_missing_facts(self):
        drug = {"system": "ATC5", "code": "B01AA03", "route": "oral", "dose_form": "tablet"}
        contexts = [({"pregnant": False}, "checked"), ({"pregnant": True}, "insufficient_information"),
                    ({"pregnant": True, "mechanical_heart_valve": False}, "issues_found"),
                    ({"pregnant": True, "mechanical_heart_valve": True,
                      "high_thromboembolism_risk": True}, "insufficient_information"),
                    ({"pregnant": True, "mechanical_heart_valve": True,
                      "high_thromboembolism_risk": True, "warfarin_benefit_outweighs_risk": True}, "checked"),
                    ({"pregnant": True, "mechanical_heart_valve": True,
                      "high_thromboembolism_risk": True, "warfarin_benefit_outweighs_risk": False}, "issues_found")]
        for context, status in contexts:
            with self.subTest(context=context):
                self.assertEqual(check(*fixture(drug, context))["status"], status)

    def test_atc3_never_promoted_using_ground_truth(self):
        case, rec = fixture({"system": "ATC3", "code": "A10B"}, {"egfr_ml_min_1_73m2": 10})
        case["medications"] = [{"system": "ATC5", "code": "A10BA02"}]
        result = check(case, rec)
        self.assertEqual(result["status"], "insufficient_information")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["coverage"]["checked_rule_count"], 0)
        self.assertEqual(result["missing_fields"][0]["reason"], "ingredient_identity_unknown")

    def test_scope_never_guessed(self):
        case, rec = fixture({"system": "ATC5", "code": "A10BA02"}, {"egfr_ml_min_1_73m2": 10})
        self.assertEqual(check(case, rec)["status"], "insufficient_information")
        rec["candidates"][0]["drug"].update(route="intravenous", dose_form="tablet")
        self.assertEqual(check(case, rec)["status"], "not_checked")

    def test_uncovered_and_draft_are_not_passed(self):
        self.assertEqual(check(*fixture({"system": "ATC5", "code": "fictional-uncovered"}))["status"], "not_checked")
        rules = copy.deepcopy(self.rules)
        for rule in rules:
            rule["review_status"] = "draft"
        result = check(*fixture(context={"egfr_ml_min_1_73m2": 1}), rules)
        self.assertEqual(result["status"], "not_checked")
        self.assertEqual(result["applied_rules"], [])
        self.assertEqual(check(*fixture(), [])["status"], "not_checked")

    def test_precedence_and_candidates_are_not_changed(self):
        case, rec = fixture(context={"egfr_ml_min_1_73m2": 20})
        rec["candidates"].extend([{"drug": {"system": "ATC3", "code": "B01A"}, "score": .7},
                                  {"drug": {"system": "ATC3", "code": "N02A"}, "score": .8}])
        before = copy.deepcopy((case, rec))
        result = check(case, rec)
        self.assertEqual(result["status"], "issues_found")
        self.assertEqual(result["coverage"]["pending_rule_count"], 1)
        self.assertEqual(result["coverage"]["checked_candidate_count"], 1)
        self.assertEqual(len(result["findings"]), 1)
        self.assertTrue(any(x["code"] == "candidate_not_covered" for x in result["unchecked_reasons"]))
        self.assertEqual((case, rec), before)

    def test_input_contract_and_synthetic_boundary(self):
        case, rec = fixture(context={"egfr_ml_min_1_73m2": 20})
        rec["case_id"] = "other"
        self.assertEqual(check(case, rec)["status"], "not_checked")
        rec["case_id"] = case["case_id"]
        rec["status"] = "unsupported_input"
        self.assertEqual(check(case, rec)["status"], "not_checked")
        rec["status"] = "ok"
        case["data_kind"] = rec["data_kind"] = "restricted"
        rules = copy.deepcopy(self.rules)
        for rule in rules:
            rule["origin"] = "synthetic_fixture"
        self.assertEqual(check(case, rec, rules)["status"], "not_checked")

    def test_model_input_does_not_include_reference_answer(self):
        value = source_input(self.rules[2])
        self.assertEqual(set(value), {"source", "source_text_kind", "source_text", "drug_scope", "allowed_predicates"})
        self.assertNotIn("condition", value)
        self.assertNotIn("statement", value)

    def test_generated_conditions_grammar_and_missing_exception(self):
        reference = self.rules[2]
        original = compare_condition(reference, reference["condition"])
        self.assertTrue(original["matches_finite_reference"])
        self.assertEqual(original["synthetic_context_count"], 81)
        incomplete = {"field": "pregnant", "op": "eq", "value": True}
        self.assertFalse(compare_condition(reference, incomplete)["matches_finite_reference"])
        self.assertFalse(assess_candidate(reference, {"statement": {}, "condition": reference["condition"]})["valid"])
        with self.assertRaises(ValueError):
            validate_condition({"field": "invented", "op": "eq", "value": True}, reference["required_fields"])
        with self.assertRaises(ValueError):
            validate_condition({"not": incomplete, "all": [incomplete]}, reference["required_fields"])

    def test_output_schema_has_no_clinical_threshold_or_gold_tree(self):
        import json
        schema = output_schema(["fictional_temperature", "fictional_cooler"])
        serialized = json.dumps(schema)
        self.assertIn("fictional_temperature", serialized)
        self.assertNotIn("egfr", serialized)
        self.assertNotIn("30", serialized)
        self.assertEqual(schema["properties"]["statement"], {"type": "string"})

    def test_reviewed_model_package_executes_only_accepted_rules(self):
        rules = load_rules(DEFAULT_RULES.with_name("medication-llm-reviewed-v2.json"))
        self.assertEqual([r["review_status"] for r in rules], ["reviewed", "reviewed", "rejected"])
        for value, status in [(20, "issues_found"), (30, "checked"), (-1, "insufficient_information")]:
            self.assertEqual(check(*fixture(context={"egfr_ml_min_1_73m2": value}), rules)["status"], status)
        drug = {"system": "ATC5", "code": "M01AE01", "route": "oral", "dose_form": "tablet"}
        self.assertEqual(check(*fixture(drug, {"perioperative_cabg": True}), rules)["status"], "issues_found")
        drug["code"] = "B01AA03"
        report = check(*fixture(drug, {"pregnant": True, "mechanical_heart_valve": False}), rules)
        self.assertEqual(report["status"], "not_checked")
        self.assertEqual(report["findings"], [])
        self.assertTrue(any(x["code"] == "rule_disabled" and x["review_status"] == "rejected"
                            for x in report["unchecked_reasons"]))


if __name__ == "__main__":
    unittest.main()
