"""Download or inspect the official April 2020 Synthea CSV sample locally."""

import argparse
import csv
import json
from pathlib import Path
import shutil
from urllib.request import urlopen
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
URL = "https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_csv_apr2020.zip"
DEST = ROOT / "data/local/synthea-apr2020"
FILES = {
    "patients.csv": {"Id"},
    "encounters.csv": {"Id", "PATIENT", "START"},
    "conditions.csv": {"PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"},
    "procedures.csv": {"PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"},
    "medications.csv": {"PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"},
    "allergies.csv": {"PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        archive = ROOT / ".cache/synthea_sample_data_csv_apr2020.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            partial = archive.with_suffix(".zip.part")
            try:
                with urlopen(URL, timeout=45) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output)
                with ZipFile(partial) as source:
                    names = {Path(info.filename).name for info in source.infolist()}
                    if not set(FILES).issubset(names):
                        raise ValueError("The archive is missing required sample tables")
                partial.replace(archive)
            finally:
                partial.unlink(missing_ok=True)
        DEST.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive) as source:
            for info in source.infolist():
                name = Path(info.filename).name
                if name in FILES and not (DEST / name).exists():
                    with source.open(info) as entry, (DEST / name).open("wb") as output:
                        shutil.copyfileobj(entry, output)
    counts = {}
    for name, required in FILES.items():
        with (DEST / name).open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"{name}: required columns missing")
            counts[name] = sum(1 for _ in reader)
            if not counts[name]:
                raise ValueError(f"{name}: empty table")
    print(json.dumps({"dataset": "synthea-csv-apr2020", "kind": "synthetic", "source": URL, "tables": counts}, indent=2))


if __name__ == "__main__":
    main()
