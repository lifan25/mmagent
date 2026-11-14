"""Local medication agent: existing SSPNet -> sourced rules -> explicit next action."""

import argparse
import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "0.1-draft"
DEFAULT_AGENT_RULES = ROOT / "src/knowledge/rules/medication-llm-reviewed-v2.json"
CASE_FIELDS = ("contract_version", "data_kind", "case_id", "diagnoses", "procedures", "history", "context")


class MedicationAgent:
    def __init__(self, recommender=None, rules=None, checker=None):
        if rules is None:
            from src.knowledge.check import load_rules
            rules = load_rules(DEFAULT_AGENT_RULES)
        if recommender is None:
            from src.recommendation.predict import SSPNetRecommender
            recommender = SSPNetRecommender()
        if checker is None:
            from src.knowledge.check import check
            checker = check
        self.recommender, self.rules, self.checker = recommender, rules, checker

    def run_with_scores(self, case):
        """Return the public report and a separate local evaluation record; infer once."""
        if not isinstance(case, dict):
            raise ValueError("Expected a Case object, not a dataset record or a list")
        missing = [name for name in CASE_FIELDS if name not in case]
        forbidden = {"medications", "target_medications", "target", "label"} & set(case)
        if missing or forbidden:
            raise ValueError(f"Case boundary violation; missing={missing}, answer_fields={sorted(forbidden)}")
        if case["contract_version"] != CONTRACT:
            raise ValueError(f"Unsupported contract_version; expected {CONTRACT}")
        # Pass only the shared Case. Evaluation labels stay outside this object.
        clean = {name: case[name] for name in CASE_FIELDS}
        local_scores = self.recommender.score_case(clean)
        recommendation = local_scores["recommendation"]
        if any(recommendation.get(k) != clean[k] for k in ("contract_version", "data_kind", "case_id")):
            raise ValueError("Recommendation identity/version does not match the input Case")
        trace = [{"tool": "validate_case", "status": "accepted"},
                 {"tool": "sspnet.recommend", "status": recommendation["status"],
                  "model_version": recommendation["model_version"]}]
        report = {name: clean[name] for name in ("contract_version", "data_kind", "case_id")}
        report.update(execution="tool_orchestration", recommendation=recommendation, check_report=None, trace=trace)
        if recommendation["status"] != "ok":
            report.update(status=recommendation["status"],
                          next_action="resolve_input_issues", requested_information=recommendation["input_issues"])
            trace.append({"tool": "knowledge.check", "status": "skipped", "reason": "recommendation_not_ok"})
            return report, local_scores
        original_candidates = copy.deepcopy(recommendation["candidates"])
        checked = self.checker(clean, recommendation, self.rules)
        if recommendation["candidates"] != original_candidates:
            raise ValueError("Flag-only knowledge checks must not alter the original candidates")
        if any(checked.get(k) != clean[k] for k in ("contract_version", "data_kind", "case_id")):
            raise ValueError("Knowledge report identity/version does not match the input Case")
        actions = {"issues_found": ("review_required", "review_flagged_candidates"),
                   "insufficient_information": ("needs_information", "provide_missing_facts"),
                   "not_checked": ("not_checked", "review_uncovered_scope"),
                   "checked": ("completed", "review_candidates_and_coverage")}
        status, action = actions[checked["status"]]
        report.update(status=status, next_action=action, check_report=checked,
                      requested_information=checked["missing_fields"])
        trace.append({"tool": "knowledge.check", "status": checked["status"],
                      "applied_rules": checked["applied_rules"],
                      "loaded_rules": [{"rule_id": r["rule_id"], "version": r["version"],
                                        "review_status": r["review_status"]} for r in self.rules]})
        # Candidate sets are never rewritten by the checker or the agent.
        return report, local_scores

    def run(self, case):
        return self.run_with_scores(case)[0]


def read_case(path, index=0):
    if index < 0:
        raise ValueError("Case index must be nonnegative")
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as stream:
            for i, line in enumerate(stream):
                if i == index:
                    row = json.loads(line)
                    break
            else:
                raise ValueError("Requested case index is outside the input file")
    else:
        if index:
            raise ValueError("--index is only supported for JSONL inputs")
        row = json.loads(path.read_text(encoding="utf-8"))
    # A1 records keep current targets next to Case, never inside the tool input.
    return row["case"] if "case" in row else row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Case JSON or existing A1 JSONL")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--rules", type=Path, help="Defaults to the reviewed LLM package; specify reference rules for the control")
    parser.add_argument("--output", type=Path, required=True, help="New local result file; cases are not committed")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve it and choose another path")
    rules = None
    if args.rules:
        from src.knowledge.check import load_rules
        rules = load_rules(args.rules)
    report = MedicationAgent(rules=rules).run(read_case(args.input, args.index))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"output": str(args.output), "status": report["status"],
                      "next_action": report["next_action"],
                      "candidate_count": len(report["recommendation"]["candidates"])}))
