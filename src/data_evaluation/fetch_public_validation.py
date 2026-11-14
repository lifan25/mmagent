"""Fetch only the two approved public development datasets; never access MIMIC-IV full."""

import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DDI_COMMIT = "9872bb0c3e28cd03a7d460cdde3f01e0e8a26542"
DDI_BASE = f"https://raw.githubusercontent.com/AIChemist-Lab/LLM-Uncertainty-DDI/{DDI_COMMIT}"
MIMIC_BASE = "https://physionet.org/files/mimic-iv-demo/2.2"
MIMIC_TABLES = ("patients", "admissions", "diagnoses_icd", "procedures_icd", "prescriptions")


def fetch(folder, filename, url):
    path = folder / filename
    if not path.exists():
        request = Request(url, headers={"User-Agent": "mmagent-public-data-preparation"})
        with urlopen(request, timeout=60) as response:
            payload = response.read(10_000_001)
        if len(payload) > 10_000_000:
            raise ValueError(f"Unexpected public file size: {filename}")
        with path.open("xb") as output:
            output.write(payload)
    payload = path.read_bytes()
    return {
        "filename": filename,
        "url": url,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def read_table(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        return reader.fieldnames, rows


def manifest(folder, info):
    path = folder / "source.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        old_files = {item["filename"]: item["sha256"] for item in previous["files"]}
        new_files = {item["filename"]: item["sha256"] for item in info["files"]}
        if old_files != new_files:
            raise ValueError(f"Local source files changed: {folder.name}")
    else:
        info["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ddi_dir = ROOT / "data/local/llm-uncertainty-ddi"
    ddi_dir.mkdir(parents=True, exist_ok=True)
    ddi_files = [
        fetch(ddi_dir, "drug5.csv", f"{DDI_BASE}/data/drug5.csv"),
        fetch(ddi_dir, "LICENSE", f"{DDI_BASE}/LICENSE"),
    ]
    fields, rows = read_table(ddi_dir / "drug5.csv")
    expected = [f"Drug {number}" for number in range(1, 7)] + [
        "Total number of drugs", "Full Drug list with doses", "DDI", "Classification"
    ]
    if fields != expected or len(rows) != 250:
        raise ValueError("DDI benchmark does not match the approved 250-row schema")
    ddi_files[0].update({"columns": fields, "rows": len(rows)})
    ddi_summary = {
        "rows": len(rows),
        "classification_counts": dict(sorted(Counter(row["Classification"].strip().upper() for row in rows).items())),
        "drug_count_distribution": dict(sorted(Counter(row["Total number of drugs"] for row in rows).items())),
    }
    manifest(ddi_dir, {
        "dataset": "LLM-Uncertainty-DDI", "commit": DDI_COMMIT,
        "source_page": "https://github.com/AIChemist-Lab/LLM-Uncertainty-DDI",
        "license": "Repository MIT LICENSE; retained without modification",
        "purpose": "Held-out DDI checker benchmark preparation only; no patient histories or model tuning",
        "files": ddi_files, "aggregate_summary": ddi_summary,
    })

    mimic_dir = ROOT / "data/local/mimic-iv-demo-2.2"
    mimic_dir.mkdir(parents=True, exist_ok=True)
    mimic_files = [fetch(mimic_dir, "LICENSE.txt", f"{MIMIC_BASE}/LICENSE.txt")]
    mimic_summary = {}
    for table in MIMIC_TABLES:
        filename = f"{table}.csv.gz"
        item = fetch(mimic_dir, filename, f"{MIMIC_BASE}/hosp/{filename}")
        fields, rows = read_table(mimic_dir / filename)
        if not fields or "subject_id" not in fields:
            raise ValueError(f"Invalid MIMIC-IV Demo table: {table}")
        item.update({"columns": fields, "rows": len(rows)})
        mimic_files.append(item)
        mimic_summary[table] = {"rows": len(rows), "bytes": item["bytes"]}
        if table == "patients" and len(rows) != 100:
            raise ValueError("MIMIC-IV Demo does not contain the expected 100 patient rows")
    manifest(mimic_dir, {
        "dataset": "MIMIC-IV Clinical Database Demo", "version": "2.2",
        "source_page": "https://physionet.org/content/mimic-iv-demo/2.2/",
        "license": "Open Data Commons Open Database License v1.0",
        "purpose": "Public schema development subset; not full MIMIC-IV or an independent clinical test cohort",
        "files": mimic_files, "aggregate_summary": mimic_summary,
    })
    print(json.dumps({"ddi": ddi_summary, "mimic_iv_demo": mimic_summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
