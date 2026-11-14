import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.knowledge.evaluate_ddi_lists import FIELDS, case_records, evaluate, freeze_split, parse_response, prepare, reference_pair, score


def fictional_input(key="fictional-1"):
    return {"case_id": key, "drug1": "Fictional Alpha", "drug2": "Fictional Beta",
            "drug3": "Fictional Gamma", "drug4": "", "drug5": "", "drug6": "", "doses": "fictional doses"}


class DDIListEvaluationTests(unittest.TestCase):
    def test_fixed_disjoint_exhaustive_split(self):
        split = freeze_split(250)
        self.assertEqual(split, freeze_split(250))
        self.assertEqual([len(split[key]) for key in ("pilot", "development", "sealed")], [50, 5, 195])
        self.assertEqual(len(set().union(*map(set, split.values()))), 250)
        self.assertFalse(set(split["pilot"]) & set(split["development"]))
        with self.assertRaises(ValueError):
            freeze_split(249)

    def test_reference_case_whitespace_and_ambiguity(self):
        row = {f"Drug {slot}": value for slot, value in enumerate(["fictional   ALPHA", "Fictional Beta", "", "", "", ""], 1)}
        row["DDI"] = "Fictional Beta and fictional alpha"
        self.assertEqual(reference_pair(row), ([1, 2], []))
        row["Drug 3"] = "Fictional Alpha"
        pair, issues = reference_pair(row)
        self.assertIsNone(pair)
        self.assertEqual(issues[0]["reason"], "ambiguous_name")
        row["DDI"] = "Fictional Beta and Fictional Delta"
        self.assertEqual(reference_pair(row)[1][0]["reason"], "unmapped_name")

    def test_response_preserves_original_slots_and_rejects_bad_schema(self):
        case = fictional_input()
        self.assertEqual(parse_response('{"target_pair":[2,1]}', case), ("answered", [1, 2], None))
        self.assertEqual(parse_response({"target_pair": "unknown"}, case)[0], "unknown")
        for value in ("not json", {}, {"target_pair": [1, 4]}, {"target_pair": [1, 1]},
                      {"target_pair": [True, 2]}, {"target_pair": [0, 2]},
                      {"target_pair": [1, 2], "reason": "extra"}):
            self.assertEqual(parse_response(value, case)[0], "invalid")

    def test_denominators_keep_mapping_issues_unknown_invalid_and_missing(self):
        inputs = [fictional_input(f"fictional-{i}") for i in range(5)]
        labels = [{"case_id": row["case_id"], "target_pair": [1, 2], "mapping_issues": []} for row in inputs]
        labels[1].update(target_pair=None, mapping_issues=["synthetic ambiguity"])
        responses = [{"case_id": f"fictional-{i}", "response": value} for i, value in enumerate([
            {"target_pair": [2, 1]}, {"target_pair": [1, 3]}, {"target_pair": "unknown"}, "bad json"])]
        result = score(inputs, labels, responses)
        self.assertEqual(result["counts"]["mapping_issue_lists"], 1)
        self.assertEqual(result["counts"]["missing"], 1)
        self.assertEqual(result["metrics"]["answer_coverage"]["value"], 2/5)
        self.assertEqual(result["metrics"]["interaction_localization_exact_match"]["value"], 1/4)
        self.assertEqual(result["metrics"]["answered_precision_on_mappable_references"]["value"], 1)
        with self.assertRaises(ValueError):
            score(inputs, labels, responses + [responses[0]])

    def test_no_answers_has_undefined_precision(self):
        case = fictional_input()
        result = score([case], [{"case_id": case["case_id"], "target_pair": [1, 2], "mapping_issues": []}], [])
        self.assertIsNone(result["metrics"]["answered_precision_on_mappable_references"]["value"])
        self.assertEqual(result["metrics"]["interaction_localization_exact_match"]["value"], 0)

    def test_permutation_is_label_independent_and_maps_reference_without_leakage(self):
        row = {key: "" for key in FIELDS}
        row.update({"Drug 1": "Fictional Alpha", "Drug 2": "Fictional Beta", "Drug 4": "Fictional Gamma",
                    "DDI": "Fictional Alpha and Fictional Beta", "Classification": "fictional",
                    "Full Drug list with doses": "Fictional Alpha then Beta then Gamma; synthetic doses"})
        case, label = case_records(row, 17, permuted=True)
        self.assertEqual(case, case_records(row, 17, permuted=True)[0])
        self.assertEqual(case["doses"], "")
        self.assertEqual(set(case), {"case_id", "doses", *[f"drug{i}" for i in range(1, 7)]})
        mapping = label["original_to_presented_slots"]
        self.assertEqual(label["target_pair"], sorted([mapping[1], mapping[2]]))
        for original, presented in mapping.items():
            self.assertEqual(case[f"drug{presented}"], row[f"Drug {original}"])
        changed = {**row, "DDI": "Fictional Gamma and Fictional Alpha", "Classification": "another fictional class"}
        other_case, other_label = case_records(changed, 17, permuted=True)
        self.assertEqual(case, other_case)
        self.assertEqual(other_label["target_pair"], sorted([mapping[4], mapping[1]]))
        unmappable = {**row, "DDI": "Fictional Missing and Fictional Beta"}
        self.assertIsNone(case_records(unmappable, 17, permuted=True)[1]["target_pair"])

    def test_prepare_evaluate_roundtrip_separates_labels_and_freezes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "fictional.csv"
            row = {key: "" for key in FIELDS}
            row.update({"Drug 1": "Fictional Alpha", "Drug 2": "Fictional Beta",
                        "Total number of drugs": "2", "Full Drug list with doses": "fictional doses",
                        "DDI": "Fictional Alpha and Fictional Beta", "Classification": "fictional"})
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows([row] * 250)
            prepared = base / "prepared"
            manifest = prepare(source, prepared)
            inputs = [json.loads(line) for line in (prepared / "development.inputs.jsonl").read_text().splitlines()]
            self.assertEqual(set(inputs[0]), {"case_id", "doses", *[f"drug{i}" for i in range(1, 7)]})
            self.assertEqual(manifest["sealed_lists"], 195)
            self.assertFalse((prepared / "sealed.inputs.jsonl").exists())
            responses = base / "fictional-responses.jsonl"
            responses.write_text("".join(json.dumps({"case_id": item["case_id"], "response": {"target_pair": [2, 1]}})+"\n" for item in inputs))
            report = evaluate(prepared, responses, "development", base / "results")
            self.assertEqual(report["counts"]["exact_matches"], 5)
            with (prepared / "development.inputs.jsonl").open("a") as handle:
                handle.write("\n")
            with self.assertRaises(ValueError):
                evaluate(prepared, responses, "development", base / "modified-results")


if __name__ == "__main__":
    unittest.main()
