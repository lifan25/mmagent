"""Read same-encounter facts from the existing Synthea archive, without drug targets.

This is retrospective checking at encounter end, not admission-time prediction.
No previous-encounter measurement or missing procedure is promoted to a current fact.
"""

import argparse
import copy
import csv
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from .cohort import timestamp

ROOT = Path(__file__).resolve().parents[2]
VERSION = "synthea-same-encounter-context-v1"
EGFR_CODE = "33914-3"
CABG_CODE = "232717009"


def egfr_value(row):
    """Accept indexed eGFR only; preserve the 2020 export's explicit unit alias."""
    if row.get("CODE") != EGFR_CODE or row.get("TYPE") != "numeric":
        return None, "not_numeric_egfr"
    unit = row.get("UNITS", "")
    legacy = unit == "mL/min" and "1.73" in row.get("DESCRIPTION", "")
    if unit != "mL/min/{1.73_m2}" and not legacy:
        return None, "unsupported_egfr_unit"
    try:
        value = float(row["VALUE"])
    except (ValueError, TypeError):
        return None, "invalid_egfr_value"
    if not math.isfinite(value) or value < 0:
        return None, "invalid_egfr_value"
    return value, "indexed_description_unit_alias" if legacy else "explicit_indexed_unit"


def encounter_fact(visit, observations, procedures):
    start, stop = timestamp(visit["admitted_at"]), timestamp(visit["discharged_at"])
    if start is None or stop is None or stop < start:
        raise ValueError("Invalid encounter interval")
    audit, evidence = Counter(), []
    valid = []
    for row in observations:
        if row.get("CODE") != EGFR_CODE:
            continue
        moment = timestamp(row.get("DATE", ""))
        if row.get("PATIENT") != visit["patient_id"]:
            raise ValueError("Observation patient/encounter mismatch")
        if moment is None or not start <= moment <= stop:
            audit["egfr_outside_encounter_interval"] += 1
            continue
        value, state = egfr_value(row)
        audit[state] += 1
        if value is not None:
            valid.append((moment, value, row, state))
    egfr = None
    if valid:
        latest = max(item[0] for item in valid)
        last = [item for item in valid if item[0] == latest]
        if len({item[1] for item in last}) == 1:
            egfr = last[0][1]
            evidence.extend({"field": "egfr_ml_min_1_73m2", "source": "csv/observations.csv",
                             "code_system": "LOINC", "code": EGFR_CODE,
                             "recorded_at": item[2]["DATE"], "value": item[1],
                             "original_units": item[2]["UNITS"], "unit_policy": item[3]}
                            for item in last)
        else:
            audit["conflicting_latest_egfr"] += 1
    cabg = None
    for row in procedures:
        if row.get("CODE") != CABG_CODE:
            continue
        if row.get("PATIENT") != visit["patient_id"]:
            raise ValueError("Procedure patient/encounter mismatch")
        moment = timestamp(row.get("DATE", ""))
        if moment is not None and start <= moment <= stop:
            cabg = True
            evidence.append({"field": "perioperative_cabg", "source": "procedures.csv",
                             "code_system": "SNOMED-CT", "code": CABG_CODE,
                             "recorded_at": row["DATE"]})
        else:
            audit["cabg_outside_encounter_interval"] += 1
    return {"egfr_ml_min_1_73m2": egfr, "perioperative_cabg": cabg,
            "context_version": VERSION, "knowledge_cutoff": visit["discharged_at"],
            "knowledge_time_scope": "retrospective same-encounter facts through encounter end",
            "knowledge_fact_provenance": evidence}, audit


def apply_context(case, snapshot):
    if snapshot.get("version") != VERSION:
        raise ValueError("Unexpected context snapshot version")
    facts = snapshot["cases"][case["case_id"]]
    result = copy.deepcopy(case)
    result["context"].update(facts)
    return result


def prepare(a1_dir, archive, raw_dir, output):
    if output.exists():
        raise ValueError("Context output exists; choose a new version")
    # Only identity, split and Case are used here; current medication targets are ignored.
    with (a1_dir / "main_prediction_examples.jsonl").open(encoding="utf-8") as stream:
        cases = {r["case"]["case_id"]: r["split"] for r in map(json.loads, stream)}
    with (a1_dir / "main_visits.jsonl").open(encoding="utf-8") as stream:
        visits = {r["visit_id"]: r for r in map(json.loads, stream)
                  if f"{r['dataset']}:{r['visit_id']}" in cases}
    observations, procedures = defaultdict(list), defaultdict(list)
    with zipfile.ZipFile(archive) as z, z.open("csv/observations.csv") as member:
        for row in csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig")):
            if row["CODE"] == EGFR_CODE and row["ENCOUNTER"] in visits:
                observations[row["ENCOUNTER"]].append(row)
    with (raw_dir / "procedures.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["CODE"] == CABG_CODE and row["ENCOUNTER"] in visits:
                procedures[row["ENCOUNTER"]].append(row)
    result, totals, by_split = {}, Counter(), defaultdict(Counter)
    for key, visit in visits.items():
        cid = f"{visit['dataset']}:{key}"
        fact, audit = encounter_fact(visit, observations[key], procedures[key])
        result[cid] = fact
        totals.update(audit)
        counts = by_split[cases[cid]]
        counts["cases"] += 1
        counts["known_egfr"] += fact["egfr_ml_min_1_73m2"] is not None
        counts["known_current_cabg_positive"] += fact["perioperative_cabg"] is True
    if set(cases) != set(result):
        raise ValueError("Context must preserve every original A1 prediction case")
    payload = {"version": VERSION, "source_a1": str(a1_dir), "archive": str(archive),
               "unit_source": "https://loinc.org/33914-3/",
               "policy": "Same encounter only, latest valid eGFR at/before discharge; conflicting latest values unknown. "
                         "Legacy mL/min accepted only with exact indexed LOINC and description containing 1.73. "
                         "CABG recorded within encounter gives true; missing never gives false. "
                         "No drug targets or future encounters used; this is retrospective, not prospective advice.",
               "summary": {"splits": dict(by_split), "audit": dict(totals)}, "cases": result}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--a1-dir", type=Path, default=ROOT / "data/processed/data_evaluation/synthea-apr2020-v3")
    p.add_argument("--archive", type=Path, default=ROOT / ".cache/synthea_sample_data_csv_apr2020.zip")
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data/local/synthea-apr2020")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    prepare(args.a1_dir, args.archive, args.raw_dir, args.output)
