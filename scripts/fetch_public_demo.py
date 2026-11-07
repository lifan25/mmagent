"""Fetch or validate the five public MIMIC-III demo tables used for preparation."""

import argparse
import csv
import json
from pathlib import Path
import shutil
from urllib.request import urlopen


BASE_URL = "https://physionet.org/files/mimiciii-demo/1.4/"
DESTINATION = Path(__file__).resolve().parents[1] / "data/public/mimiciii-demo-1.4"
HEADERS = {
    "PATIENTS.csv": {"SUBJECT_ID"},
    "ADMISSIONS.csv": {"SUBJECT_ID", "HADM_ID", "ADMITTIME"},
    "DIAGNOSES_ICD.csv": {"SUBJECT_ID", "HADM_ID", "ICD9_CODE"},
    "PROCEDURES_ICD.csv": {"SUBJECT_ID", "HADM_ID", "ICD9_CODE"},
    "PRESCRIPTIONS.csv": {"SUBJECT_ID", "HADM_ID", "NDC"},
}


def validate_table(path, required_headers):
    subjects = set()
    row_count = 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        field_map = {name.upper(): name for name in (reader.fieldnames or [])}
        missing = required_headers - set(field_map)
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        for row in reader:
            subjects.add(row[field_map["SUBJECT_ID"]])
            row_count += 1
    if not row_count:
        raise ValueError(f"{path.name}: empty data")
    return {"rows": row_count, "patients": len(subjects)}, subjects


def download(name):
    destination = DESTINATION / name
    if destination.exists():
        return
    partial = destination.with_name(destination.name + ".part")
    try:
        with urlopen(BASE_URL + name, timeout=60) as response:
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output)
        if name in HEADERS:
            validate_table(partial, HEADERS[name])
        elif "Open Database License" not in partial.read_text(encoding="utf-8"):
            raise ValueError("The downloaded file is not the expected demo license")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        DESTINATION.mkdir(parents=True, exist_ok=True)
        for name in [*HEADERS, "LICENSE.txt"]:
            download(name)
    summary, subject_sets = {}, {}
    for name, required in HEADERS.items():
        summary[name], subject_sets[name] = validate_table(DESTINATION / name, required)
    patients = subject_sets["PATIENTS.csv"]
    if len(patients) != 100:
        raise ValueError("Expected the official 100-patient demo")
    for name, subjects in subject_sets.items():
        if not subjects.issubset(patients):
            raise ValueError(f"{name}: patient does not belong to demo PATIENTS")
    if not (DESTINATION / "LICENSE.txt").is_file():
        raise ValueError("The public demo license is missing")
    print(json.dumps({"dataset": "mimiciii-demo-1.4", "tables": summary}, indent=2))


if __name__ == "__main__":
    main()
