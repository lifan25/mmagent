"""Bounded, local-only BIBM-inspired source formalization and self-review experiment."""

import argparse
import copy
import hashlib
import itertools
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from src.knowledge.check import DEFAULT_RULES, evaluate_condition, load_rules

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = Path(__file__).with_name("prompts")


def validate_condition(node, allowed_fields):
    if not isinstance(node, dict):
        raise ValueError("Condition node must be an object")
    if set(node) in ({"all"}, {"any"}):
        children = next(iter(node.values()))
        if not isinstance(children, list) or not children:
            raise ValueError("Logical list must be nonempty")
        for child in children:
            validate_condition(child, allowed_fields)
    elif set(node) == {"not"}:
        validate_condition(node["not"], allowed_fields)
    elif set(node) in ({"field", "op", "value"}, {"field", "op", "value", "minimum"}):
        if node["field"] not in allowed_fields:
            raise ValueError("Unknown predicate: " + str(node["field"]))
        if node["op"] not in {"eq", "lt"} or not isinstance(node["value"], (bool, int, float)):
            raise ValueError("Unsupported comparison")
        if isinstance(node["value"], bool) and node["op"] != "eq":
            raise ValueError("Boolean values require eq")
    else:
        raise ValueError("Mixed or unsupported condition grammar")


def compare_condition(reference, proposed):
    """Finite synthetic truth-table check; not clinical accuracy or a proof of equivalence."""
    try:
        validate_condition(proposed, reference["required_fields"])
        fields = reference["required_fields"]
        values = [([-1, 0, 29.9, 30, 45, None] if field == "egfr_ml_min_1_73m2"
                   else [False, True, None]) for field in fields]
        mismatch, total = 0, 0
        for combination in itertools.product(*values):
            context = dict(zip(fields, combination))
            expected = evaluate_condition(reference["condition"], context)
            observed = evaluate_condition(proposed, context)
            mismatch += observed != expected
            total += 1
        return {"valid": True, "synthetic_context_count": total, "mismatch_count": mismatch,
                "matches_finite_reference": mismatch == 0}
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        return {"valid": False, "error": str(error), "matches_finite_reference": False}


def source_input(rule):
    """Explicit allowlist: no reference condition/statement, cases, or medication labels."""
    return {"source": rule["source"], "source_text_kind": rule["evidence"]["type"],
            "source_text": rule["evidence"]["text"], "drug_scope": rule["selector"],
            "allowed_predicates": rule["predicate_definitions"]}


def assess_candidate(reference, candidate):
    result = compare_condition(reference, candidate.get("condition"))
    if not isinstance(candidate.get("statement"), str) or not candidate["statement"].strip():
        result.update(valid=False, matches_finite_reference=False, error="statement must be a nonempty string")
    return result


def output_schema(allowed_fields):
    """Constrain syntax and field names, without supplying a source-specific condition."""
    forms = []
    for operator in ("all", "any", "not"):
        value = {"$ref": "#/$defs/node"} if operator == "not" else {
            "type": "array", "minItems": 1, "items": {"$ref": "#/$defs/node"}}
        forms.append({"type": "object", "properties": {operator: value},
                      "required": [operator], "additionalProperties": False})
    forms.append({"type": "object", "properties": {
        "field": {"type": "string", "enum": list(allowed_fields)},
        "op": {"type": "string", "enum": ["eq", "lt"]},
        "value": {"anyOf": [{"type": "boolean"}, {"type": "number"}]},
        "minimum": {"type": "number"}},
        "required": ["field", "op", "value"], "additionalProperties": False})
    return {"type": "object", "properties": {"statement": {"type": "string"},
            "condition": {"$ref": "#/$defs/node"}}, "required": ["statement", "condition"],
            "additionalProperties": False, "$defs": {"node": {"anyOf": forms}}}


def run(output, runtime, rules_path=DEFAULT_RULES, port=18081, prompt_version="v2", resume=False):
    output, runtime, rules_path = Path(output), Path(runtime), Path(rules_path)
    if output.exists() and not resume:
        raise ValueError("Preserve prior runs; choose a new output directory")
    if resume and not (output / "run-info.json").exists():
        raise ValueError("Resume requires a saved run")
    source = json.loads(runtime.read_text(encoding="utf-8"))
    references = load_rules(rules_path)
    schemas = {rule["rule_id"]: output_schema(rule["required_fields"]) for rule in references}
    prompts = {phase: (PROMPTS / f"bibm-medication-{phase}-{prompt_version if phase == 'extract' else 'v1'}.txt").read_text(encoding="utf-8")
               for phase in ("extract", "review")}
    settings = {"model": "qwen3-4b-instruct-2507-q4km", "temperature": 0, "top_p": 1,
                "seed": 20261114, "stream": False, "response_format": {"type": "json_object"}}
    output.mkdir(parents=True, exist_ok=resume)
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
        "method": "BIBM-inspired constrained formalization; curated source paraphrases, predefined predicates, one self-review and at most one rewrite; no MLN diagnosis",
        "source_preparation": "Agent located official labels and authored faithful paraphrases before local model calls; not automated web retrieval/summarization",
        "endpoint": f"http://127.0.0.1:{port}/v1/chat/completions", "settings": settings,
        "repository_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime_source": source, "runtime_source_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        "reference_file": str(rules_path), "reference_sha256": hashlib.sha256(rules_path.read_bytes()).hexdigest(),
        "code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in ("extract.py", "check.py")},
        "prompt_version": prompt_version,
        "generation_schemas": schemas if prompt_version == "v2" else None,
        "prompts": prompts, "rules": len(references), "max_rewrites": 1, "self_score_threshold": 15,
        "review_limitation": "Self-score and finite reference agreement cannot authorize a rule; all generated candidates remain draft."}
    info_path = output / "run-info.json"
    records = []
    if resume:
        previous = json.loads(info_path.read_text(encoding="utf-8"))
        if previous.get("status") == "completed":
            raise ValueError("Completed runs cannot be resumed")
        for key in ("endpoint", "settings", "reference_sha256", "runtime_source_sha256", "prompts", "generation_schemas"):
            if previous[key] != manifest[key]:
                raise ValueError("Resume changed frozen configuration: " + key)
        previous.setdefault("resume_events", []).append({"utc": manifest["started_utc"],
            "code_sha256": manifest["code_sha256"], "reason": "Resume saved requests without resampling"})
        manifest = previous
        records = [json.loads(line) for line in (output / "raw-calls.jsonl").read_text(encoding="utf-8").splitlines()]
    info_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    cached = {(item["rule_id"], item["stage"]): item for item in records}
    candidates, checks = [], []
    started = time.perf_counter()
    with (output / "raw-calls.jsonl").open("a" if resume else "x", encoding="utf-8") as raw:
        def call(rule_id, stage, prompt, data, limit):
            payload = {**settings, "max_tokens": limit, "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}
            if prompt_version == "v2" and stage != "self_review":
                payload["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "medication_condition", "strict": True, "schema": schemas[rule_id]}}
            record = cached.get((rule_id, stage))
            if record is not None:
                if record["request"] != payload:
                    raise ValueError("Saved request differs; refusing to resample")
                text = record["response"]
            else:
                begin = time.perf_counter()
                req = Request(manifest["endpoint"], data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=240) as response:
                    result = json.load(response)
                choice = result["choices"][0]
                text = choice["message"]["content"]
                record = {"rule_id": rule_id, "stage": stage, "request": payload, "response": text,
                          "finish_reason": choice.get("finish_reason"), "usage": result.get("usage", {}),
                          "seconds": time.perf_counter()-begin}
                raw.write(json.dumps(record, ensure_ascii=False)+"\n")
                raw.flush()
                records.append(record)
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {"parse_error": "not an object"}
            except json.JSONDecodeError as error:
                return {"parse_error": str(error)}

        for reference in references:
            data = source_input(reference)
            initial = call(reference["rule_id"], "generate", prompts["extract"], data, 768)
            initial_check = assess_candidate(reference, initial)
            feedback = call(reference["rule_id"], "self_review", prompts["review"],
                {**data, "candidate": initial,
                 "comparison_warning": None if initial_check["matches_finite_reference"]
                 else "Finite synthetic boundary/unknown checks failed."}, 384)
            score = feedback.get("score")
            rewrite = (not initial_check["matches_finite_reference"] or not isinstance(score, (int, float))
                       or score < 15 or feedback.get("rewrite_needed") is True)
            final = call(reference["rule_id"], "rewrite", prompts["extract"],
                         {**data, "previous_candidate": initial, "review": feedback}, 768) if rewrite else initial
            candidate = copy.deepcopy(reference)
            candidate.update(origin="local_llm_extraction", statement=final.get("statement"),
                             condition=final.get("condition"), review_status="draft",
                             review_record={"date": datetime.now(timezone.utc).date().isoformat(),
                                 "author": settings["model"], "reviewer": None,
                                 "scope": "Pending independent source/logic review; self-score does not approve execution."})
            candidates.append(candidate)
            checks.append({"rule_id": reference["rule_id"], "initial": initial_check,
                           "self_review": feedback, "rewritten": rewrite,
                           "final": assess_candidate(reference, final)})
            print(json.dumps(checks[-1], ensure_ascii=True), flush=True)
    (output / "draft-rules.json").write_text(json.dumps({"rules": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"rule_count": len(references), "calls": len(records), "review_status": "draft",
               "initial_finite_reference_matches": sum(x["initial"]["matches_finite_reference"] for x in checks),
               "final_finite_reference_matches": sum(x["final"]["matches_finite_reference"] for x in checks),
               "rewrites": sum(x["rewritten"] for x in checks), "checks": checks,
               "limitation": "Three curated source summaries and finite synthetic checks only; not end-to-end extraction accuracy or clinical validation."}
    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.update(status="completed", seconds=sum(item["seconds"] for item in records),
                    last_process_seconds=time.perf_counter()-started,
                    token_usage={key: sum(x["usage"].get(key, 0) for x in records)
                                 for key in ("prompt_tokens", "completion_tokens")})
    info_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--prompt-version", choices=["v1", "v2"], default="v2")
    parser.add_argument("--resume", action="store_true", help="Reuse exactly matching saved calls after interruption")
    args = parser.parse_args()
    run(args.output, args.runtime, args.rules, args.port, args.prompt_version, args.resume)
