"""Prepare a small, label-blind MedPIC annotation pilot; no model or clinical labels."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from src.data_evaluation.fetch_public_validation import fetch


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "9ef6db4f13865b14fc2e6be3f94dcfaf3a0cf983"
BASE = f"https://huggingface.co/datasets/TIM0927/MedPIC-Bench/resolve/{COMMIT}"
FILE_HASHES = {
    "README.md": "cdb119c7fae1e99baaca21ffae334b027006fa8a2ff544782c4ce46766fad535",
    "questions.json": "c28c054ed788de7cbaf7592883e90ef85e530cf9464019dfd39618dcc5ea4ae6",
}
SOURCE = ROOT / "data/local/medpic-bench-20261114"
OUTPUT = ROOT / "data/processed/data_evaluation/medpic-development-v1"
PILOT_SIZE = 20


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def save_new(files):
    """Idempotent creation, refusing to replace any edited annotation or frozen input."""
    for path, text in files.items():
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise ValueError(f"Existing file differs; preserve it and use a new output folder: {path}")
    for path, text in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)


def download(folder):
    folder.mkdir(parents=True, exist_ok=True)
    files = [fetch(folder, name, f"{BASE}/{name}") for name in FILE_HASHES]
    for item in files:
        if item["sha256"] != FILE_HASHES[item["filename"]]:
            raise ValueError(f"Unexpected fixed source: {item['filename']}")
    source_path = folder / "source.json"
    if not source_path.exists():
        save_new({source_path: dump({
            "dataset": "MedPIC-Bench", "commit": COMMIT, "license": "CC-BY-4.0",
            "repository_url": "https://huggingface.co/datasets/TIM0927/MedPIC-Bench",
            "license_evidence_url": f"{BASE}/README.md", "files": files,
            "paper_url": "https://arxiv.org/abs/2608.03028", "official_split": "test",
        })})


def read_source(folder):
    for name, expected in FILE_HASHES.items():
        if digest((folder / name).read_bytes()) != expected:
            raise ValueError(f"Changed fixed source file: {name}")
    metadata = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    if metadata["commit"] != COMMIT:
        raise ValueError("Unexpected MedPIC source version")
    rows = json.loads((folder / "questions.json").read_text(encoding="utf-8"))
    if len(rows) != 467 or len({r["instance_id"] for r in rows}) != len(rows):
        raise ValueError("Expected 467 distinct source records")
    for row in rows:
        if not all(isinstance(row[k], str) and row[k].strip()
                   for k in ("instance_id", "patient_vignette", "question")):
            raise ValueError("Missing input text")
        if set(row["options"]) != set("ABCDE") or not all(
            isinstance(v, str) and v.strip() for v in row["options"].values()
        ):
            raise ValueError("Expected five nonempty options")
        # Validate labels structurally, without using their values to select or adapt inputs.
        if not isinstance(row["answer"], list) or not row["answer"] or not all(
            k in row["options"] for k in row["answer"]
        ) or len(set(row["answer"])) != len(row["answer"]):
            raise ValueError("Invalid author answer IDs")
    return rows


def select_development(rows, count=PILOT_SIZE):
    # Original question text only. Ties use source position, never answers or taxonomy.
    return sorted(enumerate(rows), key=lambda item: (
        digest(item[1]["question"].encode("utf-8")), item[0]
    ))[:count]


def payload(row):
    return {key: row[key] for key in ("patient_vignette", "question", "options")}


def question_hint(question):
    """Lexical triage only, not a clinical eligibility label."""
    text = question.casefold()
    avoid = bool(re.search(r"avoid|contraindicat|inappropriate|not appropriate|not recommended", text))
    dose = bool(re.search(r"dose|dosage|dosing", text))
    caution = bool(re.search(r"caution|monitor", text))
    if dose:
        return "mixed_avoidance_dose" if avoid else "dose_decision"
    if caution:
        return "mixed_avoidance_caution" if avoid else "caution_monitoring"
    return "avoidance_screen" if avoid else "other_or_uncertain"


def annotation_record(case):
    return {
        "case_key": case["case_key"], "review_status": "pending",
        "eligibility": {"decision": None, "action": None, "reason": None},
        "facts": [],
        "candidates": [{
            "option_id": key, "entity_type": None, "drug_name": None,
            "ingredient_rxcui": None, "dose": None, "route": None, "formulation": None,
            "mapping_status": "unreviewed", "evidence": [],
        } for key in case["input"]["options"]],
        "checks": [], "notes": None,
    }


def prepare(source, output):
    rows = read_source(source)
    selected = select_development(rows)
    inputs, reference, provenance = [], [], []
    for position, row in selected:
        case_key = "medpic-" + digest(row["instance_id"].encode("utf-8"))[:16]
        inputs.append({"case_key": case_key, "input": payload(row)})
        reference.append({"case_key": case_key, "author_answer_ids": row["answer"]})
        provenance.append({"case_key": case_key, "source_item_id": row["instance_id"],
                           "source_row": position, "question_sha256": digest(row["question"].encode("utf-8"))})
    question_counts = Counter(row["question"] for row in rows)
    summary = {
        "protocol": "medpic-development-v1", "source_commit": COMMIT,
        "source_sha256": FILE_HASHES["questions.json"],
        "source_records": len(rows), "source_options": sum(len(r["options"]) for r in rows),
        "development_records": len(inputs), "development_options": sum(len(c["input"]["options"]) for c in inputs),
        "not_selected_for_development": len(rows) - len(inputs),
        "source_unique_question_texts": len(question_counts),
        "source_records_with_repeated_question": sum(n for n in question_counts.values() if n > 1),
        "development_unique_question_texts": len({c["input"]["question"] for c in inputs}),
        "development_question_hints": dict(sorted(Counter(question_hint(c["input"]["question"]) for c in inputs).items())),
        "completed_human_annotations": 0, "clinical_labels_created": 0,
        "model_calls": 0, "checker_predictions": 0,
        "status": "input_and_annotation_preparation_only",
        "limitations": [
            "Official test is used here as a development resource; unused rows are not a verified independent test split.",
            "No released pair IDs, source-rule IDs, per-item citations or RxNorm mappings.",
            "Question hints are lexical triage, pending human eligibility review.",
            "Author non-selection is not clinical clearance; answer options are not co-administered drugs.",
        ],
    }
    input_text = dump(inputs)
    files = {
        output / "inputs.development.json": input_text,
        output / "author-reference.development.json": dump(reference),
        output / "manifest.json": dump({
            "protocol": summary["protocol"], "source_commit": COMMIT,
            "source_sha256": FILE_HASHES["questions.json"], "selection": "SHA256(original question UTF-8), then zero-based source row; first 20",
            "inputs_sha256": digest(input_text.encode("utf-8")), "development": provenance,
            "remaining_status": "unused_for_local_tuning_not_an_independent_test_split",
        }),
        output / "summary.json": dump(summary),
    }
    for role in ("B", "C"):
        files[output / f"annotations_{role}.json"] = dump({
            "protocol": summary["protocol"], "assigned_role": role,
            "reviewer": None, "reviewer_kind": None,
            "records": [annotation_record(case) for case in inputs],
        })
    save_new(files)
    return summary


def check_annotations(path, prepared):
    """Check completeness and quoted input evidence, not medical correctness."""
    inputs_path = prepared / "inputs.development.json"
    manifest = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
    if digest(inputs_path.read_bytes()) != manifest["inputs_sha256"]:
        raise ValueError("Frozen development inputs changed")
    inputs = {r["case_key"]: r["input"] for r in json.loads(inputs_path.read_text(encoding="utf-8"))}
    pack = json.loads(path.read_text(encoding="utf-8"))
    records = pack["records"]
    if len(records) != len(inputs) or {r["case_key"] for r in records} != set(inputs):
        raise ValueError("Annotation records must cover all development inputs exactly once")
    counts = Counter()
    for record in records:
        status = record["review_status"]
        if status not in {"pending", "draft", "complete"}:
            raise ValueError("Unknown review status")
        counts[status] += 1
        original = inputs[record["case_key"]]
        options = [r["option_id"] for r in record["candidates"]]
        if len(options) != len(original["options"]) or set(options) != set(original["options"]):
            raise ValueError("Candidate annotations cannot drop or duplicate an option")
        for item in record["facts"] + record["candidates"]:
            for evidence in item.get("evidence", []):
                field, quote = evidence["field"], evidence["quote"]
                text = original["options"].get(field[8:]) if field.startswith("options.") else original.get(field)
                if not isinstance(text, str) or not quote or quote not in text:
                    raise ValueError("Evidence must quote an exact span of the indicated input field")
                start, end = evidence["start"], evidence["end"]
                if (type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(text) or text[start:end] != quote):
                    raise ValueError("Evidence offsets must reproduce the exact Unicode input span")
        if status == "complete":
            if not pack.get("reviewer") or pack.get("reviewer_kind") not in {"human", "ai_draft"}:
                raise ValueError("Completed transcription requires attribution")
            eligibility = record["eligibility"]
            if eligibility["decision"] not in {"in_scope", "out_of_scope", "uncertain"} or not eligibility["reason"]:
                raise ValueError("Completed transcription requires eligibility and reason")
            if any(not item["entity_type"] for item in record["candidates"]):
                raise ValueError("Completed transcription requires candidate entity types")
            if eligibility["decision"] == "in_scope":
                if eligibility["action"] not in {"avoid", "contraindication", "inappropriate"}:
                    raise ValueError("In-scope transcription requires the precise avoidance action")
                if any(item["mapping_status"] not in {
                    "unresolved", "ingredient_only", "product_verified", "not_applicable"
                } for item in record["candidates"]):
                    raise ValueError("In-scope candidates need reviewed mapping states; unresolved is allowed")
                if not record["facts"]:
                    raise ValueError("In-scope transcription must document reported or missing facts")
                for fact in record["facts"]:
                    if not all(k in fact for k in ("field", "raw_value", "raw_unit", "value", "unit", "status", "time", "evidence")):
                        raise ValueError("Fact transcription is missing required fields")
                    if fact["status"] not in {"explicit_positive", "explicit_negative", "not_reported", "conflicting"}:
                        raise ValueError("Unknown fact status")
                    if fact["status"] == "not_reported":
                        if fact["value"] is not None or fact["raw_value"] is not None:
                            raise ValueError("Unreported facts must remain null")
                    elif not fact["evidence"]:
                        raise ValueError("Reported or conflicting facts require input evidence")
    return {"records": len(records), "status_counts": dict(counts),
            "reviewer_kind": pack.get("reviewer_kind"), "checks": "input_structure_and_evidence_only",
            "clinical_correctness_validated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--check-annotations", type=Path)
    args = parser.parse_args()
    if args.check_annotations:
        result = check_annotations(args.check_annotations, args.output)
    else:
        if args.download:
            download(args.source)
        result = prepare(args.source, args.output)
    print(dump(result), end="")


if __name__ == "__main__":
    main()
