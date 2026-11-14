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
from datetime import date
from pathlib import Path

from .cohort import timestamp

ROOT = Path(__file__).resolve().parents[2]
VERSION = "synthea-same-encounter-context-v1"
EXPANDED_VERSION = "synthea-recorded-context-v2"
EGFR_CODE = "33914-3"
CABG_CODE = "232717009"
CAD_CODE = "53741008"


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
    if snapshot.get("version") not in {VERSION, EXPANDED_VERSION}:
        raise ValueError("Unexpected context snapshot version")
    facts = snapshot["cases"][case["case_id"]]
    result = copy.deepcopy(case)
    result["context"].update(facts)
    return result


def recorded_patient_facts(visit, patient, conditions, encounters):
    """Use recorded CAD, never absence of diagnoses as a negative disease fact."""
    start, cutoff = timestamp(visit["admitted_at"]), timestamp(visit["discharged_at"])
    if start is None or cutoff is None or cutoff < start or patient["Id"] != visit["patient_id"]:
        raise ValueError("Invalid patient or encounter boundary")
    audit, evidence = Counter(), []
    age = None
    try:
        birth = date.fromisoformat(patient["BIRTHDATE"])
        if birth <= cutoff.date():
            today = cutoff.date()
            age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            evidence.append({"field": "age_years", "source": "patients.csv", "birth_date": birth.isoformat(),
                             "as_of": visit["discharged_at"], "value": age})
    except (ValueError, TypeError):
        pass
    if age is None:
        audit["birth_date_missing_or_invalid"] += 1
    cad = None
    for row in conditions:
        if row.get("CODE") != CAD_CODE:
            continue
        source = encounters.get(row.get("ENCOUNTER"))
        if row.get("PATIENT") != visit["patient_id"] or (source and source["PATIENT"] != visit["patient_id"]):
            raise ValueError("CAD patient/source encounter mismatch")
        if source is None:
            audit["cad_source_encounter_missing"] += 1
            continue
        recorded_start, recorded_stop = timestamp(source["START"]), timestamp(source["STOP"])
        if recorded_start is None or recorded_stop is None or recorded_stop < recorded_start:
            audit["cad_source_interval_invalid"] += 1
            continue
        same_encounter = row["ENCOUNTER"] == visit["visit_id"]
        if (same_encounter and recorded_stop > cutoff) or (not same_encounter and recorded_stop >= start):
            audit["cad_source_not_available"] += 1
            continue
        try:
            diagnosed = date.fromisoformat(row["START"])
            resolved = date.fromisoformat(row["STOP"]) if row.get("STOP") else None
        except (ValueError, TypeError):
            audit["cad_condition_dates_invalid"] += 1
            continue
        if diagnosed > recorded_stop.date() or (resolved and resolved < diagnosed):
            audit["cad_condition_source_date_conflict"] += 1
            continue
        if diagnosed < recorded_start.date():
            audit["cad_diagnosis_precedes_source_encounter"] += 1
        if diagnosed > cutoff.date():
            audit["cad_diagnosis_after_cutoff"] += 1
            continue
        if resolved and resolved <= cutoff.date():
            # A date-only resolution on the cutoff day cannot locate the resolution relative to the encounter.
            audit["cad_resolved_by_cutoff_or_same_day_ambiguous"] += 1
            continue
        cad = True
        audit["cad_same_encounter" if same_encounter else "cad_prior_record_unresolved_at_cutoff"] += 1
        evidence.append({"field": "coronary_artery_disease", "source": "conditions.csv",
                         "code_system": "SNOMED-CT", "code": CAD_CODE,
                         "source_encounter_id": row["ENCOUNTER"], "source_encounter_ended_at": source["STOP"],
                         "source_encounter_started_at": source["START"],
                         "diagnosed_date": row["START"], "value": True,
                         "interpretation": "Source-recorded CAD with no resolution recorded by cutoff; not clinical adjudication."})
    return {"age_years": age, "coronary_artery_disease": cad}, evidence, audit


def extend_recorded_context(a1_dir, raw_dir, base_path, output):
    if output.exists():
        raise ValueError("Context output exists; choose a new version")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("version") != VERSION:
        raise ValueError("Extension requires the preserved v1 context")
    with (a1_dir / "main_prediction_examples.jsonl").open(encoding="utf-8") as stream:
        cases = {r["case"]["case_id"]: r["split"] for r in map(json.loads, stream)}
    if set(cases) != set(base["cases"]):
        raise ValueError("Original context and A1 cohorts differ")
    with (a1_dir / "main_visits.jsonl").open(encoding="utf-8") as stream:
        visits = {f"{r['dataset']}:{r['visit_id']}": r for r in map(json.loads, stream)}
    def rows(name):
        with (raw_dir / name).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    patients = {r["Id"]: r for r in rows("patients.csv")}
    encounters = {r["Id"]: r for r in rows("encounters.csv")}
    conditions = defaultdict(list)
    for row in rows("conditions.csv"):
        if row["CODE"] == CAD_CODE:
            conditions[row["PATIENT"]].append(row)
    expanded, totals, counts = {}, Counter(), defaultdict(Counter)
    for cid, split in cases.items():
        visit = visits[cid]
        added, provenance, audit = recorded_patient_facts(visit, patients[visit["patient_id"]],
                                                          conditions[visit["patient_id"]], encounters)
        facts = copy.deepcopy(base["cases"][cid])
        facts.update(added, context_version=EXPANDED_VERSION,
                     knowledge_time_scope="retrospective encounter end; same-encounter measurements and previously documented unresolved CAD")
        facts["knowledge_fact_provenance"].extend(provenance)
        expanded[cid] = facts
        totals.update(audit)
        counts[split].update(cases=1, known_age=added["age_years"] is not None,
                             recorded_cad_positive=added["coronary_artery_disease"] is True,
                             known_egfr=facts["egfr_ml_min_1_73m2"] is not None,
                             known_current_cabg_positive=facts["perioperative_cabg"] is True)
    payload = {"version": EXPANDED_VERSION, "parent_context": str(base_path), "source_a1": str(a1_dir),
               "source_dictionary": "https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary",
               "policy": base["policy"] + " Age is completed years at encounter end. CAD is exact SNOMED 53741008, "
                         "recorded in the same encounter or an encounter ended before current start, with no resolution "
                         "recorded by current end. Resolution on cutoff date is ambiguous. Missing/resolved records do not "
                         "become false. Later resolution dates are censored, not exposed as current facts. No other diseases "
                         "or pregnancy inferred from open condition intervals.",
               "summary": {"splits": dict(counts), "audit": dict(totals)}, "cases": expanded}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(payload["summary"], indent=2))


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
    p.add_argument("--base-context", type=Path, help="Extend preserved v1 facts with recorded age/CAD; no old measurements recomputed")
    args = p.parse_args()
    if args.base_context:
        extend_recorded_context(args.a1_dir, args.raw_dir, args.base_context, args.output)
    else:
        prepare(args.a1_dir, args.archive, args.raw_dir, args.output)
