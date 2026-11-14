"""Source-grounded rule formalization and a restricted BIBM diagnosis run."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

import numpy as np

from src.knowledge.mln import ConditionalMLN, SCHEMA, validate_rules

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "outputs/dxy-diaformer-seed8"
VOCAB = ROOT / "third_party/Diaformer/data/dxy_dataset/vocab.txt"
SOURCES = ROOT / "src/knowledge/rules/bibm-dxy-sources-v1.json"
PROMPT = ROOT / "src/knowledge/prompts/bibm-diagnosis-formalize-v1.txt"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vocabulary():
    symptom_block, disease_block = VOCAB.read_text(encoding="utf-8").strip().split("\n\n")
    return disease_block.splitlines(), [x for x in symptom_block.splitlines() if not x.startswith("[")]


def new_output(path):
    path = Path(path).resolve()
    if not path.is_relative_to((ROOT / "outputs/knowledge").resolve()):
        raise ValueError("Keep run artifacts inside ignored outputs/knowledge")
    path.mkdir(parents=True, exist_ok=False)
    return path


def positive_evidence(prediction, mode="inquired"):
    """Labels and unasked hidden symptoms never become inference features."""
    if mode not in {"explicit", "inquired"}:
        raise ValueError("Unknown observation mode")
    explicit = prediction["explicit_symptoms"]
    positive = {s for s, answer in explicit.items() if answer is True}
    if mode == "inquired":
        hidden = prediction["implicit_symptoms"]
        for symptom in prediction["inquiry_symptom"]:
            if symptom not in explicit and hidden.get(symptom) is True:
                positive.add(symptom)
    return sorted(positive)


def validate_source_rules(document, diseases, symptoms, sources):
    rules = validate_rules(document, diseases, symptoms)
    by_source = {row["source_id"]: row for row in sources}
    for rule in rules:
        if rule["source_id"] not in by_source or by_source[rule["source_id"]]["disease"] != rule["disease"]:
            raise ValueError("Rule source does not support its disease domain")
    return rules


def extract_rules(output, port, structured=False):
    output = new_output(output)
    diseases, symptoms = vocabulary()
    sources = read_json(SOURCES)
    prompt = PROMPT.read_text(encoding="utf-8")
    model_source = ROOT / "models/knowledge/qwen3-4b-instruct-2507-q4km/source.json"
    settings = {"model": "qwen3-4b-instruct-2507-q4km", "temperature": 0, "top_p": 1,
                "seed": 20261114, "max_tokens": 600, "stream": False,
                "cache_prompt": False, "response_format": {"type": "json_object"}}
    if structured:
        settings["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "diagnosis_rule_candidates", "strict": True,
            "schema": {"type": "object", "properties": {"rules": {"type": "array", "maxItems": 4,
                "items": {"type": "object", "properties": {
                    "symptoms": {"type": "array", "minItems": 1, "maxItems": 3,
                                 "items": {"type": "string", "enum": symptoms}},
                    "rationale": {"type": "string"}},
                    "required": ["symptoms", "rationale"], "additionalProperties": False}}},
                "required": ["rules"], "additionalProperties": False}}}
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
                "source_sha256": digest(SOURCES), "prompt_sha256": digest(PROMPT),
                "model_source": read_json(model_source), "request_settings": settings,
                "endpoint": f"http://127.0.0.1:{port}/v1/chat/completions",
                "scope": "LLM formalization only; agent-curated source selection and paraphrases; no human review or patients"}
    runtime_path = ROOT / "outputs/knowledge/bibm-local-inference-20261114/server-process.json"
    if runtime_path.exists():
        manifest["runtime_launch_record"] = read_json(runtime_path)
    write_json(output / "run-info.json", manifest)
    write_json(output / "source-summaries.json", sources)
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    rules, responses = [], []
    start = time.perf_counter()
    for source in sources["sources"]:
        payload = {**settings, "messages": [{"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps({**source, "allowed_symptoms": symptoms}, ensure_ascii=False)}]}
        request = Request(manifest["endpoint"], data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=180) as response:
            value = json.load(response)
        responses.append({"source_id": source["source_id"], "request": payload, "response": value})
        write_json(output / "raw-responses.json", responses)
        choice = value["choices"][0]
        if choice["finish_reason"] != "stop":
            raise RuntimeError("Truncated extraction retained; do not silently repair or retry")
        body = json.loads(choice["message"]["content"])
        if not isinstance(body.get("rules"), list) or len(body["rules"]) > 4:
            raise ValueError("Model did not obey the bounded rule schema")
        for index, row in enumerate(body["rules"], 1):
            rules.append({"id": f"{source['source_id']}-{index}", "disease": source["disease"],
                          "symptoms": row["symptoms"], "source_id": source["source_id"],
                          "rationale": row.get("rationale", ""), "status": "research_candidate"})
        print(json.dumps({"completed_sources": len(responses), "total_sources": len(sources["sources"])}), flush=True)
    document = {"schema_version": SCHEMA, "origin": "local_llm_formalization_of_cited_paraphrases",
                "not_clinically_reviewed": True, "rules": rules}
    try:
        validate_source_rules(document, diseases, symptoms, sources["sources"])
    except ValueError as error:
        manifest.update(status="validation_failed", error=str(error), seconds=time.perf_counter() - start)
        write_json(output / "run-info.json", manifest)
        raise
    write_json(output / "rules.json", document)
    manifest.update(status="completed", seconds=time.perf_counter() - start,
                    rules=len(rules), rules_by_disease=dict(Counter(x["disease"] for x in rules)),
                    rules_sha256=digest(output / "rules.json"))
    write_json(output / "run-info.json", manifest)
    print(json.dumps({"status": "completed", "rules": len(rules), "seconds": manifest["seconds"]}), flush=True)


def training_data():
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_diagnosis_data import DataOnlyUnpickler
    path = ROOT / "third_party/Diaformer/data/dxy_dataset/goal_set.p"
    with path.open("rb") as source:
        data = DataOnlyUnpickler(source).load()
    split = read_json(BASELINE / "split_indices.json")
    train_ids, val_ids = split["train"], split["validation"]
    if set(train_ids) & set(val_ids) or sorted(train_ids + val_ids) != list(range(len(data["train"]))):
        raise ValueError("Original train/validation split is invalid")
    return [data["train"][i] for i in train_ids], train_ids


def replay_training(output, device):
    """Inference with the existing selected checkpoint; no optimizer or updates."""
    import torch
    from src.knowledge.diaformer_baseline import load_upstream, evaluate
    output = new_output(output)
    records, ids = training_data()
    config = read_json(BASELINE / "config.json")
    checkpoint = BASELINE / "best_model.pt"
    before = digest(checkpoint)
    torch.set_num_threads(4)
    torch.manual_seed(8)
    if device == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    module = load_upstream()
    module.args = argparse.Namespace(pretrained_model=None,
        model_config=str(ROOT / "third_party/Diaformer/config/diaformer_config.json"),
        max_turn=config["max_turn"], min_probability=config["min_probability"],
        end_probability=config["end_probability"], model_output_path=None, result_output_path=None)
    module.tokenizer = module.diaTokenizer(str(VOCAB))
    model, _ = module.create_model(module.args, module.tokenizer)
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.to(device)
    start = time.perf_counter()
    metrics = evaluate(module, model, torch.device(device), records, output / "train-predictions.json")
    if digest(checkpoint) != before:
        raise RuntimeError("The original checkpoint changed during inference")
    write_json(output / "run-info.json", {"mode": "frozen_checkpoint_training_split_inference_only",
        "device": device, "training_indices": ids, "checkpoint_sha256": before,
        "split_sha256": digest(BASELINE / "split_indices.json"), "seconds": time.perf_counter() - start,
        "cases": len(records), "query_metrics": metrics, "optimizer_steps": 0,
        "empty_explicit_cases": sum(not any(v != "UNK" for v in r["goal"]["explicit_inform_slots"].values()) for r in records),
        "legacy_policy_caveat": "Diaformer seeds empty-explicit cases from first hidden symptom; this unasked seed is excluded by positive_evidence"})
    print(json.dumps({"status": "completed", "cases": len(records), "seconds": time.perf_counter() - start}), flush=True)


def metrics(probabilities, labels, diseases):
    y = np.asarray([diseases.index(label) for label in labels])
    predicted = np.argmax(probabilities, axis=1)
    matrix = np.zeros((len(diseases), len(diseases)), dtype=int)
    for actual, pred in zip(y, predicted):
        matrix[actual, pred] += 1
    f1 = []
    for d in range(len(diseases)):
        denominator = matrix[d, :].sum() + matrix[:, d].sum()
        f1.append(float(2 * matrix[d, d] / denominator) if denominator else 0.0)
    return {"cases": len(y), "correct": int(np.sum(y == predicted)),
            "accuracy": float(np.mean(y == predicted)), "macro_f1": float(np.mean(f1)),
            "negative_log_likelihood": float(-np.mean(np.log(np.maximum(probabilities[np.arange(len(y)), y], 1e-15)))),
            "confusion_matrix": matrix.tolist()}


def train_evaluate(rules_path, train_queries_path, output):
    output = new_output(output)
    diseases, symptoms = vocabulary()
    rules_document = read_json(rules_path)
    if rules_document.get("source_alignment_review", {}).get("status") != "agent_checked_before_weight_learning":
        raise ValueError("Run requires agent source-alignment review of candidates; raw generation is not reviewed evidence")
    rules = validate_source_rules(rules_document, diseases, symptoms, read_json(SOURCES)["sources"])
    if not rules or set(r["disease"] for r in rules) != set(diseases):
        raise ValueError("Need sourced candidate rules for all five disease classes")
    training, ids = training_data()
    replay_info = read_json(Path(train_queries_path).parent / "run-info.json")
    if replay_info["training_indices"] != ids or replay_info["checkpoint_sha256"] != digest(BASELINE / "best_model.pt"):
        raise ValueError("Training inquiry cache does not match the frozen split/checkpoint")
    selected_epoch = read_json(BASELINE / "summary.json")["best_epoch"]
    paths = {"train": Path(train_queries_path),
             "validation": BASELINE / f"validation-{selected_epoch:03d}.json",
             "test": BASELINE / "test-predictions.json"}
    records = {name: read_json(path) for name, path in paths.items()}
    if len(records["train"]) != len(training) or any(
            r["target_disease"] != item["disease_tag"] or
            r["explicit_symptoms"] != item["goal"]["explicit_inform_slots"] or
            r["implicit_symptoms"] != item["goal"]["implicit_inform_slots"]
            for r, item in zip(records["train"], training)):
        raise ValueError("Training inquiry records are not aligned with the original split")
    protocol = {"status": "running", "method": "restricted_exact_conditional_MLN",
        "evidence_predicate": "ObservedPositive(symptom, patient)", "hard_constraint": "exactly_one_disease",
        "l2": 0.01, "model_selection": "none; fixed settings before this run",
        "rules_sha256": digest(rules_path), "source_sha256": digest(SOURCES),
        "input_sha256": {name: digest(path) for name, path in paths.items()},
        "code_sha256": {name: digest(ROOT / "src/knowledge" / name)
                        for name in ("mln.py", "bibm_diagnosis.py")},
        "diseases": diseases, "symptoms": symptoms, "rule_count": len(rules),
        "rules_by_disease": dict(Counter(r["disease"] for r in rules)),
        "empty_explicit_by_split": {name: sum(not any(v != "UNK" for v in r["explicit_symptoms"].values()) for r in rows)
                                    for name, rows in records.items()},
        "scope": "local-LLM formalized candidate rules; no expert approval; no automatic retrieval/summarization/refinement; no Alchemy execution"}
    write_json(output / "protocol.json", protocol)
    write_json(output / "rules.json", rules_document)
    start = time.perf_counter()
    results = {}
    for mode in ("explicit", "inquired"):
        evidence = {name: [positive_evidence(r, mode) for r in rows] for name, rows in records.items()}
        train_labels = [r["target_disease"] for r in records["train"]]
        for control, candidate_rules in (("prior_only", []), ("sourced_rules", rules)):
            name = f"{mode}_{control}"
            model = ConditionalMLN(diseases, symptoms, candidate_rules).fit(evidence["train"], train_labels)
            model.save(output / f"{name}.json")
            model.export_mln(output / f"{name}.mln")
            # Predictions are produced without passing disease labels to inference.
            probabilities = {split: model.predict_proba(e) for split, e in evidence.items()}
            summary = {"fit": model.fit_info,
                "splits": {split: metrics(probabilities[split], [r["target_disease"] for r in rows], diseases)
                           for split, rows in records.items()},
                "active_rule_cases": {split: int(np.any(model.activations(e), axis=1).sum())
                                      for split, e in evidence.items()},
                "rule_activation_counts": {split: dict(zip((r["id"] for r in candidate_rules),
                    model.activations(e).sum(axis=0).astype(int).tolist())) for split, e in evidence.items()}}
            nonempty = [i for i, r in enumerate(records["test"]) if any(v != "UNK" for v in r["explicit_symptoms"].values())]
            summary["test_nonempty_explicit_sensitivity"] = metrics(probabilities["test"][nonempty],
                [records["test"][i]["target_disease"] for i in nonempty], diseases)
            results[name] = summary
            write_json(output / f"{name}-test-predictions.json", [{"case_index": i,
                "observed_positive": evidence["test"][i], "probabilities": dict(zip(diseases, p.tolist())),
                "predicted_disease": diseases[int(np.argmax(p))], "explanation": model.explain(evidence["test"][i])}
                for i, p in enumerate(probabilities["test"])])
            restored = ConditionalMLN.load(output / f"{name}.json")
            np.testing.assert_array_equal(restored.predict_proba(evidence["test"]), probabilities["test"])
        model.export_evidence(output / f"{mode}-train.db", evidence["train"], train_labels)
        model.export_evidence(output / f"{mode}-validation.db", evidence["validation"])
        model.export_evidence(output / f"{mode}-test.db", evidence["test"])
    test = records["test"]
    diaformer_correct = sum(r["pred_disease"] == r["target_disease"] for r in test)
    protocol["status"] = "completed"
    report = {"protocol": protocol, "results": results, "seconds": time.perf_counter() - start,
              "diaformer_frozen_comparator": {"correct": diaformer_correct, "cases": len(test),
                                              "accuracy": diaformer_correct / len(test)},
              "no_rule_control": "prior_only uses the same optimizer and prior unary formulas, with zero external rules",
              "status": "completed"}
    write_json(output / "summary.json", report)
    write_json(output / "protocol.json", protocol)
    print(json.dumps({"status": "completed", "seconds": report["seconds"], "results": {
        k: v["splits"]["test"] for k, v in results.items()}}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--port", type=int, default=18081)
    extract.add_argument("--structured", action="store_true", help="Enforce the same schema in local decoding")
    replay = sub.add_parser("replay-training")
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    run = sub.add_parser("run")
    run.add_argument("--rules", type=Path, required=True)
    run.add_argument("--training-queries", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        extract_rules(args.output, args.port, args.structured)
    elif args.command == "replay-training":
        replay_training(args.output, args.device)
    else:
        train_evaluate(args.rules, args.training_queries, args.output)


if __name__ == "__main__":
    main()
