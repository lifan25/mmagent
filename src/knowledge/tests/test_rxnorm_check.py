import copy
import unittest

from src.knowledge.check import DEFAULT_RULES, check, load_product_metadata, load_rules
from src.knowledge.tests.test_medication_check import fixture


class RxNormCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules(DEFAULT_RULES.with_name("medication-llm-rxnorm-scope-v1.json"))
        cls.metadata = load_product_metadata()

    def test_four_products_keep_ingredient_salt_route_and_form(self):
        expected = {
            "198405": ("5640", "5640", "317541", "not_specified"),
            "310965": ("5640", "5640", "317541", "not_specified"),
            "855332": ("11289", "114194", "317541", "not_specified"),
            "860975": ("6809", "235743", "316945", "extended_release"),
        }
        for code, (ingredient, salt, form, release) in expected.items():
            identity = self.metadata["products"][code]["identity"]
            self.assertEqual(identity["ingredient_rxcuis"], [ingredient])
            self.assertEqual(identity["active_ingredient_rxcuis"], [salt])
            self.assertEqual(identity["dose_form_rxcui"], form)
            self.assertEqual(identity["route"], "oral")
            self.assertEqual(identity["release"], release)
        self.assertEqual(self.metadata["products"]["860975"]["identity"]["quantity_factor"],
                         {"quantityFactorValue": "24", "quantityFactorUnit": "HR"})

    def test_extended_release_does_not_match_standard_tablet_only_scope(self):
        restricted = copy.deepcopy(self.rules)
        restricted[0]["selector"]["allowed_dose_form_rxcuis"] = ["317541"]
        case, rec = fixture({"system": "RxNorm", "code": "860975"}, {"egfr_ml_min_1_73m2": 10})
        result = check(case, rec, restricted)
        self.assertEqual(result["status"], "not_checked")
        self.assertTrue(any(x["code"] == "outside_label_scope" for x in result["unchecked_reasons"]))
        # The previous ATC5 package cannot silently treat a product as an ATC5 code.
        self.assertEqual(check(case, rec)["status"], "not_checked")

    def test_known_product_egfr_trigger_boundary_and_missing(self):
        for value, status in [(29.9, "issues_found"), (30, "checked"), (None, "insufficient_information"),
                              (-1, "insufficient_information")]:
            case, rec = fixture({"system": "RxNorm", "code": "860975"}, {"egfr_ml_min_1_73m2": value})
            before = copy.deepcopy(rec)
            result = check(case, rec, self.rules)
            self.assertEqual(result["status"], status)
            self.assertEqual(rec, before)
            if status == "issues_found":
                self.assertEqual(result["findings"][0]["identity"]["dose_form_rxcui"], "316945")
                self.assertEqual(result["findings"][0]["scope_evidence"][0]["rxcui"], "860975")

    def test_cabg_known_positive_negative_and_unknown(self):
        for code in ("198405", "310965"):
            for value, status in [(True, "issues_found"), (False, "checked"), (None, "insufficient_information")]:
                result = check(*fixture({"system": "RxNorm", "code": code}, {"perioperative_cabg": value}), self.rules)
                self.assertEqual(result["status"], status)

    def test_unknown_product_cannot_supply_its_own_identity(self):
        drug = {"system": "RxNorm", "code": "fictional-unknown-product", "identity":
                self.metadata["products"]["860975"]["identity"]}
        result = check(*fixture(drug, {"egfr_ml_min_1_73m2": 10}), self.rules)
        self.assertEqual(result["status"], "not_checked")
        self.assertEqual(result["findings"], [])
        self.assertTrue(any(x["code"] == "product_metadata_missing" for x in result["unchecked_reasons"]))

    def test_missing_metadata_form_is_unknown_not_a_match(self):
        metadata = copy.deepcopy(self.metadata)
        metadata["products"]["860975"]["identity"]["dose_form_rxcui"] = None
        case, rec = fixture({"system": "RxNorm", "code": "860975"}, {"egfr_ml_min_1_73m2": 10})
        self.assertEqual(check(case, rec, self.rules, metadata)["status"], "insufficient_information")

    def test_scope_adaptation_preserves_model_logic_and_rejection(self):
        original = load_rules(DEFAULT_RULES.with_name("medication-llm-reviewed-v2.json"))
        for old, new in zip(original, self.rules):
            self.assertEqual(old["condition"], new["condition"])
            self.assertEqual(old["statement"], new["statement"])
            self.assertEqual(old["review_status"], new["review_status"])
        report = check(*fixture({"system": "RxNorm", "code": "855332"},
                               {"pregnant": True, "mechanical_heart_valve": False}), self.rules)
        self.assertEqual(report["status"], "not_checked")
        self.assertEqual(report["findings"], [])

    def test_atc3_still_cannot_supply_exact_identity(self):
        case, rec = fixture({"system": "ATC3", "code": "A10B"}, {"egfr_ml_min_1_73m2": 10})
        for rules in (load_rules(), self.rules):
            result = check(case, rec, rules)
            self.assertEqual(result["status"], "insufficient_information")
            self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()
