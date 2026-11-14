"""Prepare a fixed official-test pilot and evaluate text relation extraction."""

import argparse
import json
import random
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261114
KEYWORDS = re.compile(r"interact|concomitan|co.?administ|inhibit|increas|decreas|avoid|combin|potentiat", re.I)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")


def read_corpus(path):
    rows = {"train": [], "test": []}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".xml") or "__MACOSX" in name:
                continue
            if "/Train/" in name:
                split = "train"
            elif "/Test/Test for DDI Extraction task/" in name:
                split = "test"
            else:
                continue  # DrugNER pairs are placeholders, not relation-negative labels.
            document = ET.fromstring(archive.read(name))
            for sentence in document.findall(".//sentence"):
                entities = {e.attrib["id"]: e.attrib for e in sentence.findall("entity")}
                for pair in sentence.findall("pair"):
                    assert pair.attrib["ddi"] in ("true", "false")
                    target_entities = [entities[pair.attrib[k]] for k in ("e1", "e2")]
                    rows[split].append({
                        "case_id": pair.attrib["id"], "document": name,
                        "input": {"sentence": sentence.attrib["text"],
                                  "entity1": {k: target_entities[0][k] for k in ("text", "charOffset")},
                                  "entity2": {k: target_entities[1][k] for k in ("text", "charOffset")}},
                        "target": "interaction" if pair.attrib["ddi"] == "true" else "not_stated",
                        "source_type": pair.get("type"),
                    })
    for split in rows:
        rows[split].sort(key=lambda r: r["case_id"])
        assert len({r["case_id"] for r in rows[split]}) == len(rows[split])
    assert not ({r["case_id"] for r in rows["train"]} & {r["case_id"] for r in rows["test"]})
    return rows


def prepare(source, output):
    if output.exists():
        raise ValueError("Prepared pilot exists; preserve it and choose a new directory")
    rows = read_corpus(source / "DDICorpus-2013.zip")
    selected = {
        "development": random.Random(SEED).sample(rows["train"], 5),
        "pilot": random.Random(SEED).sample(rows["test"], min(80, len(rows["test"]))),
    }
    output.mkdir(parents=True)
    summary = {}
    for name, subset in selected.items():
        subset.sort(key=lambda r: r["case_id"])
        write_jsonl(output / f"{name}-inputs.jsonl", [{"case_id": r["case_id"], "input": r["input"]} for r in subset])
        write_jsonl(output / f"{name}-labels.jsonl", [{k: r[k] for k in ("case_id", "document", "target", "source_type")} for r in subset])
        summary[name] = {"pairs": len(subset), "documents": len({r["document"] for r in subset}),
                         "labels": dict(Counter(r["target"] for r in subset))}
    report = {"source": json.loads((source / "source.json").read_text(encoding="utf-8")),
              "seed": SEED, "sample_order": "sort by original pair ID, random.sample; no label stratification",
              "official_pairs": {s: len(v) for s, v in rows.items()}, "splits": summary,
              "scope": "Binary text relation extraction; not_stated is not clinical absence of interaction."}
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary))


def parse_response(response):
    try:
        value = json.loads(response) if isinstance(response, str) else response
        if not isinstance(value, dict) or set(value) != {"relation"}:
            return "invalid"
        result = value["relation"]
        return result if isinstance(result, str) and result in ("interaction", "not_stated", "unknown") else "invalid"
    except (ValueError, TypeError):
        return "invalid"


def metrics(labels, predictions):
    counts = Counter((r["target"], predictions.get(r["case_id"], "missing")) for r in labels)
    n = len(labels)
    positives = sum(r["target"] == "interaction" for r in labels)
    negatives = n - positives
    tp, fp = counts["interaction", "interaction"], counts["not_stated", "interaction"]
    tn = counts["not_stated", "not_stated"]
    answered = sum(v for (_, p), v in counts.items() if p in ("interaction", "not_stated"))
    recall = tp/positives if positives else None
    precision = tp/(tp+fp) if tp+fp else 0.
    specificity = tn/negatives if negatives else None
    return {"samples": n, "positive": positives, "negative": negatives, "true_positive": tp,
            "false_positive": fp, "true_negative": tn, "all_sample_accuracy": (tp+tn)/n,
            "positive_precision": precision, "positive_recall": recall,
            "positive_f1": 2*tp/(positives+tp+fp) if positives+tp+fp else 0.,
            "negative_recognition_rate": specificity,
            "balanced_accuracy": (recall+specificity)/2 if recall is not None and specificity is not None else None,
            "answered": answered, "answer_coverage": answered/n,
            "answered_accuracy": (tp+tn)/answered if answered else None,
            "unknown": sum(v for (_, p), v in counts.items() if p == "unknown"),
            "invalid_or_missing": sum(v for (_, p), v in counts.items() if p in ("invalid", "missing"))}


def evaluate(prepared, responses, output, method="evaluated_model"):
    if output.exists():
        raise ValueError("Evaluation exists; choose a new report path")
    labels, inputs = read_jsonl(prepared / "pilot-labels.jsonl"), read_jsonl(prepared / "pilot-inputs.jsonl")
    results = read_jsonl(responses)
    ids = {r["case_id"] for r in labels}
    assert len({r["case_id"] for r in results}) == len(results), "Duplicate model responses"
    assert {r["case_id"] for r in results} <= ids, "Response IDs outside the frozen pilot"
    predictions = {r["case_id"]: parse_response(r["response"]) for r in results}
    report = {"task": "DDICorpus-2013 official-test exploratory 80-pair pilot", "seed": SEED,
              "prepared_manifest": str(prepared / "manifest.json"), "responses": str(responses),
              "results": {
                  "always_not_stated": metrics(labels, {i: "not_stated" for i in ids}),
                  "always_interaction": metrics(labels, {i: "interaction" for i in ids}),
                  "sentence_keyword": metrics(labels, {r["case_id"]: "interaction" if KEYWORDS.search(r["input"]["sentence"]) else "not_stated" for r in inputs}),
                  method: metrics(labels, predictions)},
              "limitations": ["One fixed exploratory pilot; model training and inference settings must accompany the result.",
                              "Pairs within a source document are dependent; no significance claim.",
                              "Public corpus pretraining contamination cannot be excluded.",
                              "Negative labels concern the supplied sentence, not clinical drug-pair safety."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["results"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "evaluate"])
    parser.add_argument("--source", type=Path, default=ROOT / "data/local/ddicorpus-2013")
    parser.add_argument("--prepared", type=Path, default=ROOT / "data/processed/knowledge/ddicorpus-pilot-v1")
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--method", default="evaluated_model")
    parser.add_argument("--report", type=Path, default=ROOT / "outputs/knowledge/ddicorpus-zero-shot-v1/evaluation.json")
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.source, args.prepared)
    else:
        if args.responses is None:
            parser.error("evaluate requires --responses")
        evaluate(args.prepared, args.responses, args.report, args.method)
