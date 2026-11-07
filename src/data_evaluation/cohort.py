"""A1 cohort preparation: raw codes, auditable filtering, patient-level splits."""

import csv
import json
import random
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


LAYOUTS = {
    "mimic": {
        "files": ["PATIENTS", "ADMISSIONS", "DIAGNOSES_ICD", "PROCEDURES_ICD", "PRESCRIPTIONS"],
        "patient": "subject_id", "patient_pk": "subject_id", "visit": "hadm_id", "visit_fk": "hadm_id",
        "start": "admittime", "stop": "dischtime", "code": "icd9_code", "med": "ndc",
        "med_start": "startdate", "systems": ["ICD9CM-diagnosis", "ICD9CM-procedure", "NDC"],
    },
    "synthea": {
        "files": ["patients", "encounters", "conditions", "procedures", "medications"],
        "patient": "PATIENT", "patient_pk": "Id", "visit": "Id", "visit_fk": "ENCOUNTER",
        "start": "START", "stop": "STOP", "code": "CODE", "med": "CODE",
        "med_start": "START", "systems": ["SNOMED-CT", "SNOMED-CT", "RxNorm"],
    },
}


def timestamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)


def read_csv(path, required):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        return list(reader)


def codes(rows, column, system):
    return [{"system": system, "code": value} for value in sorted({
        row[column].strip() for row in rows if row[column].strip() not in {"", "0"}
    })]


def normalize(data_dir, kind, dataset):
    layout = LAYOUTS[kind]
    files = layout["files"]
    patient_key, visit_key = layout["patient"], layout["visit"]
    requirements = [
        {layout["patient_pk"]},
        {patient_key, visit_key, layout["start"], layout["stop"]},
        {patient_key, layout["visit_fk"], layout["code"]},
        {patient_key, layout["visit_fk"], layout["code"]},
        {patient_key, layout["visit_fk"], layout["med"], layout["med_start"]},
    ]
    tables = [read_csv(data_dir / f"{name}.csv", required) for name, required in zip(files, requirements)]
    patients = [row[layout["patient_pk"]] for row in tables[0]]
    if len(set(patients)) != len(patients) or "" in patients:
        raise ValueError("Patient primary keys must be nonempty and unique")
    known_patients = set(patients)
    admissions = {}
    for row in tables[1]:
        key = row[visit_key]
        if not key or key in admissions:
            raise ValueError("Encounter primary keys must be nonempty and unique")
        if row[patient_key] not in known_patients:
            raise ValueError("Encounter references unknown patient")
        admissions[key] = row
    audit = Counter()
    indices = []
    for name, rows in zip(files[2:], tables[2:]):
        groups = defaultdict(list)
        for row in rows:
            key = row[layout["visit_fk"]]
            if key not in admissions:
                audit[f"{name}:orphan_rows"] += 1
                continue
            if row[patient_key] != admissions[key][patient_key]:
                raise ValueError(f"{name}: patient mismatch for encounter {key}")
            groups[key].append(row)
        indices.append(groups)
    visits = []
    for key, admission in admissions.items():
        diag, proc, med = [index[key] for index in indices]
        start, stop = timestamp(admission[layout["start"]]), timestamp(admission[layout["stop"]])
        issues = []
        if start is None:
            issues.append("invalid_start")
        if stop is None:
            issues.append("missing_or_invalid_stop")
        if start and stop and stop < start:
            issues.append("stop_before_start")
        audit.update(issues)
        records = [{"code": r[layout["med"]].strip(), "start": r[layout["med_start"]],
                    "name": r.get("drug", r.get("DESCRIPTION", ""))} for r in med]
        invalid = sum(r["code"] in {"", "0"} for r in records)
        audit["invalid_medication_code_rows"] += invalid
        visits.append({
            "dataset": dataset, "data_kind": "synthetic" if kind == "synthea" else "restricted",
            "patient_id": admission[patient_key], "visit_id": key,
            "admitted_at": admission[layout["start"]], "discharged_at": admission[layout["stop"]],
            "diagnoses": codes(diag, layout["code"], layout["systems"][0]),
            "procedures": codes(proc, layout["code"], layout["systems"][1]),
            "medications": codes(med, layout["med"], layout["systems"][2]),
            "record_counts": {"diagnoses": len(diag), "procedures": len(proc), "prescriptions": len(med)},
            "medication_records": records, "invalid_medication_code_rows": invalid, "time_issues": issues,
        })
    visits.sort(key=lambda v: (v["patient_id"], timestamp(v["admitted_at"]) or datetime.max.replace(tzinfo=timezone.utc), v["visit_id"]))
    groups = defaultdict(list)
    for visit in visits:
        groups[visit["patient_id"]].append(visit)
    for group in groups.values():
        starts = set()
        previous_end = None
        for i, visit in enumerate(group, 1):
            visit["visit_index"] = i
            start, stop = timestamp(visit["admitted_at"]), timestamp(visit["discharged_at"])
            if start:
                audit["same_start_extra_visits"] += int(start in starts)
                audit["overlapping_visits"] += int(previous_end is not None and start < previous_end)
                starts.add(start)
            if stop:
                previous_end = max(previous_end, stop) if previous_end else stop
    summary = {"source_rows": {name: len(rows) for name, rows in zip(files, tables)},
               "source_patients": len(patients), "source_visits": len(visits), "audit": dict(audit)}
    return visits, summary


def select_and_split(visits, seed, ratios, min_visits, require_procedures):
    if min_visits < 1 or len(ratios) != 3 or any(r <= 0 for r in ratios):
        raise ValueError("Require positive min_visits and three positive split weights")
    reasons = Counter()
    eligible = []
    for visit in visits:
        missing = [f"missing_{key}" for key in ("diagnoses", "medications") if not visit[key]]
        if require_procedures and not visit["procedures"]:
            missing.append("missing_procedures")
        missing.extend(visit["time_issues"])
        reasons.update(missing)
        if not missing:
            eligible.append(visit)
    counts = Counter(v["patient_id"] for v in eligible)
    selected_ids = sorted(p for p, n in counts.items() if n >= min_visits)
    if len(selected_ids) < 3:
        raise ValueError("Fewer than three eligible patients: cannot create independent nonempty splits")
    shuffled = selected_ids.copy()
    random.Random(seed).shuffle(shuffled)
    total = sum(ratios)
    n_train = int(len(shuffled) * ratios[0] / total)
    n_validation = int(len(shuffled) * ratios[1] / total)
    adjusted = min(n_train, n_validation, len(shuffled) - n_train - n_validation) < 1
    if adjusted:
        n_validation = n_test = 1
        n_train = len(shuffled) - n_validation - n_test
    split = {"train": sorted(shuffled[:n_train]), "validation": sorted(shuffled[n_train:n_train+n_validation]),
             "test": sorted(shuffled[n_train+n_validation:])}
    membership = {p: name for name, ids in split.items() for p in ids}
    selected = [dict(v, split=membership[v["patient_id"]]) for v in eligible if v["patient_id"] in membership]
    summary = {"small_sample_split_adjustment": adjusted,
               "exclusion_reason_counts_nonexclusive": dict(reasons), "eligible_visits_before_patient_filter": len(eligible),
               "eligible_patients_before_patient_filter": len(counts),
               "patients_with_at_least_two_visits": sum(n >= 2 for n in counts.values()),
               "patients_with_at_least_three_visits": sum(n >= 3 for n in counts.values()),
               "excluded_visits_by_record_filter": len(visits)-len(eligible),
               "excluded_visits_by_patient_filter": len(eligible)-len(selected),
               "selected_visits": len(selected), "selected_patients": len(selected_ids),
               "split_counts": {name: {"patients": len(ids), "visits": sum(v["split"] == name for v in selected)} for name, ids in split.items()}}
    return selected, split, summary


def prediction_examples(visits):
    """Separate current targets and only admit completed earlier encounters into history."""
    patients = defaultdict(list)
    for visit in visits:
        patients[visit["patient_id"]].append(visit)
    for group in patients.values():
        for current in group:
            now = timestamp(current["admitted_at"])
            prior = [v for v in group if timestamp(v["discharged_at"]) < now
                     and timestamp(v["admitted_at"]) < now]
            history = []
            for visit in prior:
                system = visit["medications"][0]["system"]
                meds = [{"system": system, "code": code} for code in sorted({
                    row["code"] for row in visit["medication_records"]
                    if row["code"] not in {"", "0"} and timestamp(row["start"])
                    and timestamp(row["start"]) < now
                })]
                history.append({"visit_index": visit["visit_index"], "diagnoses": visit["diagnoses"],
                                "procedures": visit["procedures"], "medications": meds})
            case = {"contract_version": "0.1-draft", "data_kind": current["data_kind"],
                    "case_id": f"{current['dataset']}:{current['visit_id']}",
                    "diagnoses": current["diagnoses"], "procedures": current["procedures"],
                    "history": history or None,
                    "context": {"allergies": None, "renal_status": None,
                                "history_scope": "retained eligible encounters; medication starts before current admission",
                                "task": "retrospective visit-set prediction; not admission-time prediction"}}
            yield {"patient_id": current["patient_id"], "split": current["split"], "case": case,
                   "target_medications": current["medications"]}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, values):
    with path.open("w", encoding="utf-8") as target:
        for value in values:
            target.write(json.dumps(value, ensure_ascii=False) + "\n")


def prepare_dataset(root, config, name):
    options = config["datasets"][name]
    output = root / options["output_dir"]
    # Refuse overwrite so a changed preparation cannot silently replace B's inputs.
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output already contains files; choose a new version directory: {output}")
    visits, raw_summary = normalize(root / options["input_dir"], name, options["dataset"])
    selected, split, summary = select_and_split(visits, config["seed"], config["split_weights"],
                                               config["min_visits"], config["require_procedures"])
    examples = list(prediction_examples(selected))
    summary["prediction_examples"] = len(examples)
    summary["examples_without_observed_history"] = sum(e["case"]["history"] is None for e in examples)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    manifest = {"schema_version": "a1-v1", "dataset": options["dataset"], "source": options["source"],
                "input_dir": options["input_dir"], "code_commit": revision.stdout.strip() or None,
                "working_tree_dirty": bool(dirty.stdout.strip()), "configuration": config,
                "rules": {"codes": "strings; trim; deduplicate by system/code; empty and 0 excluded from code sets but retained in audit records",
                          "conditions": "recorded per encounter only; no chronic-condition carry-forward",
                          "times": "ISO parsed; UTC normalization for ordering; ties by encounter ID only for determinism",
                          "history": "completed retained encounters strictly before current start; no-history is unknown, not confirmed absent",
                          "split": "sorted eligible patient IDs shuffled with local seed; floor train/validation; remainder test; if any empty with >=3 patients, allocate one validation and one test patient, rest train",
                          "data_kind": "restricted is real-record processing mode for public Demo, not a license/access claim"},
                **raw_summary, **summary}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "visits.audit.jsonl", visits)
    write_jsonl(output / "visits.jsonl", selected)
    write_jsonl(output / "prediction_examples.jsonl", examples)
    write_json(output / "split.json", split)
    write_json(output / "manifest.json", manifest)
    write_json(output / "summary.json", {**raw_summary, **summary})
    return {"dataset": options["dataset"], "output_dir": options["output_dir"], **raw_summary, **summary}
