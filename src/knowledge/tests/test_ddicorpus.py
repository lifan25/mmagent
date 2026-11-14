import unittest

from src.knowledge.evaluate_ddicorpus import metrics, parse_response


class DDICorpusTests(unittest.TestCase):
    def test_strict_output_and_unknown(self):
        self.assertEqual(parse_response('{"relation":"not_stated"}'), "not_stated")
        self.assertEqual(parse_response('{"relation":"unknown"}'), "unknown")
        self.assertEqual(parse_response('{"relation":false}'), "invalid")
        self.assertEqual(parse_response('not a JSON'), "invalid")

    def test_abstentions_and_missing_not_removed_from_denominator(self):
        labels = [{"case_id": "a", "target": "interaction"}, {"case_id": "b", "target": "interaction"},
                  {"case_id": "c", "target": "not_stated"}, {"case_id": "d", "target": "not_stated"}]
        result = metrics(labels, {"a": "interaction", "b": "unknown", "c": "not_stated"})
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["all_sample_accuracy"], .5)
        self.assertEqual(result["answer_coverage"], .5)
        self.assertEqual(result["answered_accuracy"], 1.)
        self.assertEqual(result["positive_recall"], .5)
        self.assertEqual(result["negative_recognition_rate"], .5)
        self.assertEqual(result["invalid_or_missing"], 1)


if __name__ == "__main__":
    unittest.main()
