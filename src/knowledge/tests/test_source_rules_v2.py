import copy
import unittest

from src.knowledge.check import DEFAULT_RULES, check, load_product_metadata, load_rules
from src.knowledge.tests.test_medication_check import fixture


class SourceRulesV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules(DEFAULT_RULES.with_name("medication-source-reviewed-v2.json"))
        cls.products = load_product_metadata(DEFAULT_RULES.with_name("rxnorm-rule-products-v2.json"))

    def run_check(self, codes, context=None, metadata=None):
        case, rec = fixture({"system":"RxNorm", "code":codes[0]}, context or {})
        rec["candidates"] = [{"drug":{"system":"RxNorm", "code":code}, "score":.8} for code in codes]
        before_case, before_rec = copy.deepcopy(case), copy.deepcopy(rec)
        result = check(case, rec, self.rules, metadata or self.products)
        self.assertEqual(case, before_case)
        self.assertEqual(rec, before_rec)
        return result

    def test_new_ibuprofen_scope_does_not_borrow_other_strength(self):
        result = self.run_check(["198405"], {"perioperative_cabg":True})
        self.assertEqual(result["status"], "not_checked")
        self.assertEqual(result["coverage"]["checked_rule_count"], 0)
        self.assertFalse(result["findings"])
        self.assertEqual(self.run_check(["310965"], {"perioperative_cabg":True})["status"], "issues_found")

    def test_naproxen_scope_and_missing_are_separate(self):
        for code in ("198014", "849574"):
            self.assertEqual(self.run_check([code], {"perioperative_cabg":True})["status"], "issues_found")
            self.assertEqual(self.run_check([code], {"perioperative_cabg":False})["status"], "checked")
            self.assertEqual(self.run_check([code])["status"], "insufficient_information")

    def test_cad_record_is_warning_not_contraindication(self):
        result = self.run_check(["1091392"], {"coronary_artery_disease":True})
        self.assertEqual(result["findings"][0]["classification"], "avoid_use_warning")
        self.assertEqual(result["coverage"]["checked_rule_count"], 1)
        self.assertEqual(self.run_check(["1091392"], {"hypertension":True})["status"], "insufficient_information")

    def test_full_combination_ingredients_and_salt_retained(self):
        identity = self.products["products"]["1049221"]["identity"]
        self.assertEqual(set(identity["ingredient_rxcuis"]), {"161", "7804"})
        self.assertIn("82063", identity["active_ingredient_rxcuis"])
        self.assertFalse(identity["single_ingredient"])
        self.assertTrue(identity["ingredients_complete"])

    def test_pair_counts_do_not_inflate_patient_condition_checks(self):
        result = self.run_check(["1049221", "197591"])
        self.assertEqual(result["status"], "issues_found")
        self.assertEqual(result["coverage"]["checked_rule_count"], 0)
        self.assertEqual(result["coverage"]["checked_candidate_count"], 0)
        self.assertEqual(result["pair_coverage"]["checked_pair_count"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["classification"], "potential_combination_review")
        self.assertEqual(finding["actual_concurrent_use"], "unknown")
        self.assertEqual(finding["candidate_indices"], [0,1])

    def test_pair_order_and_opioid_extended_release_do_not_change_rule(self):
        for codes in (["1860154","204892"], ["204892","1860154"]):
            result = self.run_check(codes)
            self.assertEqual(result["pair_coverage"]["checked_pair_count"], 1)
            self.assertEqual(result["findings"][0]["rule_id"], "medication.opioid_benzodiazepine.candidates")

    def test_unknown_identity_can_be_potential_partner_but_is_not_flagged(self):
        result = self.run_check(["197591", "unknown"])
        self.assertEqual(result["pair_coverage"]["pending_pair_count"], 1)
        self.assertEqual(result["pair_coverage"]["checked_pair_count"], 0)
        self.assertFalse(result["findings"])
        self.assertEqual(result["status"], "insufficient_information")

    def test_known_source_code_outside_allowlists_is_not_missing_identity(self):
        # Cetirizine is documented in the source but outside all five reviewed scopes.
        result = self.run_check(["197591", "1014676"])
        self.assertEqual(result["pair_coverage"]["pending_pair_count"], 0)
        self.assertEqual(result["pair_coverage"]["uncovered_pair_count"], 1)
        self.assertEqual(result["status"], "not_checked")
        self.assertFalse(result["missing_fields"])
        self.assertTrue(any(r["code"] == "outside_reviewed_product_scope"
                            for r in result["unchecked_reasons"]))
        self.assertNotIn("1014676", self.products["products"])
        self.assertIn("1014676", self.products["known_source_rxcuis"])

    def test_nonmatching_or_single_candidate_does_not_assert_safe_pair(self):
        result = self.run_check(["197591", "204892"])
        self.assertEqual(result["pair_coverage"]["uncovered_pair_count"], 1)
        self.assertEqual(result["status"], "not_checked")
        alone = self.run_check(["1049221"], {"previous_benzodiazepine_use":True})
        self.assertEqual(alone["pair_coverage"]["candidate_pair_count"], 0)
        self.assertFalse(alone["findings"])

    def test_incomplete_component_metadata_is_unknown(self):
        metadata = copy.deepcopy(self.products)
        metadata["products"]["1049221"]["identity"]["ingredients_complete"] = False
        result = self.run_check(["1049221", "197591"], metadata=metadata)
        self.assertEqual(result["pair_coverage"]["pending_pair_count"], 1)
        self.assertFalse(result["findings"])

    def test_rule_package_requires_explicit_metadata_and_keeps_rejection(self):
        old = load_rules(DEFAULT_RULES.with_name("medication-llm-rxnorm-scope-v1.json"))
        self.assertEqual(self.rules[2]["review_status"], "rejected")
        for before, after in zip(old, self.rules[:3]):
            self.assertEqual(before["condition"], after["condition"])
        case, rec = fixture({"system":"RxNorm", "code":"198014"}, {"perioperative_cabg":True})
        self.assertEqual(check(case, rec, self.rules)["status"], "not_checked")
        self.assertEqual(check(case, rec, self.rules, self.products)["status"], "issues_found")


if __name__ == "__main__":
    unittest.main()
