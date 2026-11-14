"""A1：Demo/Synthea 全量病例准备；保留 --patient-id 单患者查看入口。"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

if __package__:
    from .cohort import prepare_dataset
else:
    from cohort import prepare_dataset


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data/public/mimiciii-demo-1.4"
TABLES = {
    "PATIENTS": {"subject_id"},
    "ADMISSIONS": {"subject_id", "hadm_id", "admittime", "dischtime"},
    "DIAGNOSES_ICD": {"subject_id", "hadm_id", "icd9_code"},
    "PROCEDURES_ICD": {"subject_id", "hadm_id", "icd9_code"},
    "PRESCRIPTIONS": {"subject_id", "hadm_id", "ndc", "drug"},
}


def read_patient_tables(data_dir, patient_id):
    """每张表按患者筛选；CSV 字段保留为字符串，不丢失编码前导零。"""
    tables = {}
    for name, required in TABLES.items():
        with (data_dir / f"{name}.csv").open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"{name}: missing columns {required - set(reader.fieldnames or [])}")
            tables[name] = [row for row in reader if row["subject_id"] == patient_id]
    return tables


def organize_visits(tables, patient_id):
    """分别归组三类明细，再挂到住院记录上，避免多表连接产生重复组合。"""
    if len(tables["PATIENTS"]) != 1:
        raise ValueError(f"Expected one patient record for {patient_id}")
    admissions = tables["ADMISSIONS"]
    admission_ids = {row["hadm_id"] for row in admissions}
    if len(admission_ids) != len(admissions):
        raise ValueError("Duplicate admission IDs")

    groups = {}
    for name in ("DIAGNOSES_ICD", "PROCEDURES_ICD", "PRESCRIPTIONS"):
        groups[name] = defaultdict(list)
        for row in tables[name]:
            if row["hadm_id"] not in admission_ids:
                raise ValueError(f"{name}: unknown admission {row['hadm_id']}")
            groups[name][row["hadm_id"]].append(row)
    for rows in tables.values():
        if any(row["subject_id"] != patient_id for row in rows):
            raise ValueError("Rows from different patients were mixed")

    visits = []
    ordered = sorted(admissions, key=lambda row: (
        datetime.fromisoformat(row["admittime"]), row["hadm_id"]
    ))
    for visit_index, admission in enumerate(ordered, start=1):
        hadm_id = admission["hadm_id"]
        diagnoses = groups["DIAGNOSES_ICD"][hadm_id]
        procedures = groups["PROCEDURES_ICD"][hadm_id]
        prescriptions = groups["PRESCRIPTIONS"][hadm_id]
        visits.append({
            "visit_index": visit_index,
            "visit_id": hadm_id,
            "admitted_at": admission["admittime"],
            "discharged_at": admission["dischtime"],
            "diagnosis_codes": sorted({row["icd9_code"] for row in diagnoses if row["icd9_code"]}),
            "procedure_codes": sorted({row["icd9_code"] for row in procedures if row["icd9_code"]}),
            "record_counts": {"diagnoses": len(diagnoses), "procedures": len(procedures),
                              "prescriptions": len(prescriptions)},
            "source_records": {"admission": admission, "diagnoses": diagnoses,
                               "procedures": procedures, "prescriptions": prescriptions},
        })
    return {"schema_version": "patient-preview-v1", "dataset": "mimiciii-demo-1.4",
            "patient_id": patient_id, "patient": tables["PATIENTS"][0], "visits": visits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id", help="仅导出一位 Demo 患者，不做全量划分")
    parser.add_argument("--dataset", choices=["mimic", "synthea", "all"], default="all")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "configs/preparation.json")
    args = parser.parse_args()
    if args.patient_id is not None and args.dataset == "synthea":
        parser.error("--patient-id is the Demo-only teaching entry; omit it for Synthea")
    if args.patient_id is None:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        names = ["mimic", "synthea"] if args.dataset == "all" else [args.dataset]
        for name in names:
            print(json.dumps(prepare_dataset(ROOT, config, name), ensure_ascii=False, indent=2))
        return
    if not args.patient_id.isascii() or not args.patient_id.isdigit():
        parser.error("patient-id must contain ASCII digits only")
    tables = read_patient_tables(DATA_DIR, args.patient_id)
    patient = organize_visits(tables, args.patient_id)
    output = ROOT / "outputs/data_evaluation" / f"patient-{args.patient_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(patient, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for visit in patient["visits"]:
        print(visit["visit_index"], visit["visit_id"], visit["admitted_at"], visit["record_counts"])
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
