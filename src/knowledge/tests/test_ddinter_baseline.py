import csv
import tempfile
import unittest
from pathlib import Path

from src.knowledge.ddinter_baseline import FIELDS, build_index, retrieve, run


class DDInterBaselineTests(unittest.TestCase):
    def test_deduplication_conflicts_and_label_independent_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("fictional_a.csv", "fictional_b.csv")]
            records = [[("A", "Fictional Alpha", "B", "Fictional Beta", "Major"),
                        ("A", "Fictional Alpha", "C", "Fictional Gamma", "Minor")],
                       [("B", "Fictional Beta", "A", "Fictional Alpha", "Major"),
                        ("A", "Fictional Alpha", "C", "Fictional Gamma", "Moderate")]]
            for path, rows in zip(paths, records):
                with path.open("w", newline="", encoding="utf-8") as target:
                    writer = csv.writer(target)
                    writer.writerow(FIELDS)
                    writer.writerows(rows)
            names, index, summary, conflicts = build_index(paths)
            self.assertEqual(summary["unique_unordered_id_pairs"], 2)
            self.assertEqual(summary["duplicate_pair_rows"], 2)
            self.assertEqual(len(conflicts), 1)
            case = {"case_id": "fictional", "drug1": "  FICTIONAL Alpha ", "drug2": "Fictional Beta",
                    "drug3": "Fictional Gamma", "drug4": "", "drug5": "", "drug6": ""}
            result = retrieve(case, names, index)
            self.assertEqual(result["target_pair"], [1, 2])
            self.assertEqual([pair["status"] for pair in result["pair_evidence"]],
                             ["ranked_evidence", "conflicting_levels", "not_in_snapshot"])
            self.assertEqual(result, retrieve({**case, "label": "different fictional answer"}, names, index))
            self.assertNotIn("label", result)
            with self.assertRaisesRegex(ValueError, "Incomplete DDInter snapshot"):
                run(Path(tmp), Path(tmp) / "not-used", Path(tmp) / "not-created")
            self.assertFalse((Path(tmp) / "not-created").exists())
            with self.assertRaisesRegex(ValueError, "partial-named"):
                run(Path(tmp), Path(tmp) / "not-used", Path(tmp) / "complete-output", allow_partial=True)
            with self.assertRaisesRegex(ValueError, "Incomplete DDInter snapshot"):
                run(Path(tmp), Path(tmp) / "not-used", Path(tmp) / "partial-output", allow_partial=True)

    def test_unknown_levels_ambiguous_names_and_ties_never_become_negative_edges(self):
        names = {"fictional alpha": {"A"}, "fictional beta": {"B"}, "fictional gamma": {"C"}}
        case = {"case_id": "fictional", "drug1": "Fictional Alpha", "drug2": "Fictional Beta",
                "drug3": "Fictional Gamma", "drug4": "", "drug5": "", "drug6": ""}
        def edge(level):
            return {"levels": {level}, "source_files": {"fictional.csv"}, "source_row_count": 1}
        index = {("A", "B"): edge("Major"), ("A", "C"): edge("Major"), ("B", "C"): edge("Unknown")}
        result = retrieve(case, names, index)
        self.assertEqual(result["target_pair"], "unknown")
        self.assertEqual(result["decision"], "highest_level_tie")
        self.assertEqual(result["pair_evidence"][-1]["status"], "unknown_level")
        names["fictional alpha"].add("A2")
        result = retrieve(case, names, index)
        self.assertEqual(result["target_pair"], "unknown")
        self.assertEqual(result["decision"], "no_ranked_evidence")
        self.assertEqual(result["pair_evidence"][0]["status"], "ambiguous_name")
        self.assertEqual(retrieve({**case, "drug1": "Fictional Missing"}, names, index)["pair_evidence"][0]["status"], "unmatched_name")


if __name__ == "__main__":
    unittest.main()
