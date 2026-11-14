"""Download public DDI resources locally, preserving source files and licenses."""

import argparse
import csv
import hashlib
import json
import ssl
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
CORPUS_COMMIT = "819b0fa538ed83ab2a8b4f5417bba3c03249b7f3"
CORPUS_BASE = f"https://raw.githubusercontent.com/isegura/DDICorpus/{CORPUS_COMMIT}"
DDINTER_BASE = "https://ddinter.scbdd.com"
DIALMED_COMMIT = "4cd19719ad8a25e0d2cb411cdede3aea9d9e095f"
DIALMED_BASE = f"https://raw.githubusercontent.com/f-window/DialMed/{DIALMED_COMMIT}"


def fetch(folder, filename, url):
    path = folder / filename
    if not path.exists():
        request = Request(url, headers={"User-Agent": "mmagent-public-data-preparation"})
        context = None
        if url.startswith(DDINTER_BASE + "/"):
            context = ssl.create_default_context()
            context.maximum_version = ssl.TLSVersion.TLSv1_2
        with urlopen(request, timeout=30, context=context) as response:
            payload = response.read(32_000_001)
        if len(payload) > 32_000_000:
            raise ValueError(f"Unexpected public file size: {filename}")
        with path.open("xb") as output:
            output.write(payload)
    payload = path.read_bytes()
    return {"filename": filename, "url": url, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def save_source(folder, metadata, filename="source.json"):
    path = folder / filename
    retrieved_at = datetime.now(timezone.utc).isoformat()
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        expected = {item["filename"]: item["sha256"] for item in previous["files"]}
        current = {item["filename"]: item["sha256"] for item in metadata["files"]}
        if expected != current:
            raise ValueError(f"Public source files changed: {folder.name}")
        if filename == "source.json":
            return
        retrieved_at = previous.get("retrieved_at_utc", previous.get("checked_at_utc", retrieved_at))
    metadata["retrieved_at_utc"] = retrieved_at
    if path.exists() and metadata == previous:
        return
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_corpus():
    folder = ROOT / "data/local/ddicorpus-2013"
    folder.mkdir(parents=True, exist_ok=True)
    files = [fetch(folder, name, f"{CORPUS_BASE}/{name}") for name in ("DDICorpus-2013.zip", "README")]
    groups = {}
    with zipfile.ZipFile(folder / "DDICorpus-2013.zip") as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".xml") or "__MACOSX" in name:
                continue
            document = ET.fromstring(archive.read(name))
            group = str(Path(name).parent).replace("\\", "/")
            counts = groups.setdefault(group, Counter())
            counts["documents"] += 1
            counts["sentences"] += len(document.findall(".//sentence"))
            counts["entities"] += len(document.findall(".//entity"))
            for pair in document.findall(".//pair"):
                ddi = pair.get("ddi")
                label = pair.get("type", "positive_untyped") if ddi == "true" else ddi or "unlabeled"
                counts[f"pair_{label}"] += 1
    summary = {group: dict(counts) for group, counts in groups.items()}
    save_source(folder, {
        "dataset": "DDICorpus-2013", "commit": CORPUS_COMMIT,
        "source_page": "https://github.com/isegura/DDICorpus",
        "license": "CC BY-NC 4.0; author license statement retained in README",
        "files": files, "aggregate_summary": summary,
        "cautions": [
            "ddi=false denotes no annotated relation expressed by the sentence, not clinical absence of an interaction.",
            "Preserve official training and Task 9.2 testing; Task 9.1 is a different named-entity task.",
            "Public benchmark may have appeared in language model pretraining.",
        ],
    })
    print(json.dumps({"ddicorpus": summary}, ensure_ascii=False, indent=2), flush=True)


def fetch_ddinter(seven_category_snapshot=False):
    folder = ROOT / "data/local/ddinter-public-20261114"
    folder.mkdir(parents=True, exist_ok=True)
    files = [
        fetch(folder, "terms.html", f"{DDINTER_BASE}/terms/"),
    ]
    summary = {}
    pair_levels = {}
    drug_ids = set()
    categories = "ABDHLPV" if seven_category_snapshot else "ABDHLPRV"
    for category in categories:
        filename = f"ddinter_downloads_code_{category}.csv"
        item = fetch(folder, filename, f"{DDINTER_BASE}/static/media/download/{filename}")
        with (folder / filename).open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            rows = list(reader)
            fields = reader.fieldnames
        if fields != ["DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"] or not rows:
            raise ValueError(f"Expected nonempty DDInter CSV: {filename}")
        for row in rows:
            pair = tuple(sorted((row["DDInterID_A"], row["DDInterID_B"])))
            pair_levels.setdefault(pair, set()).add(row["Level"])
            drug_ids.update(pair)
        item.update({"rows": len(rows), "columns": fields})
        files.append(item)
        summary[filename] = {
            "rows": len(rows), "columns": fields, "bytes": item["bytes"],
            "level_counts": dict(Counter(row["Level"] for row in rows)),
        }
        print(json.dumps({"ddinter_file": summary[filename], "file": filename}, ensure_ascii=False), flush=True)
    combined = {
        "rows": sum(item["rows"] for item in summary.values()),
        "unique_unordered_pairs": len(pair_levels), "unique_drug_ids": len(drug_ids),
        "pairs_with_conflicting_levels": sum(len(levels) > 1 for levels in pair_levels.values()),
        "unique_pair_level_sets": dict(Counter("|".join(sorted(levels)) for levels in pair_levels.values())),
    }
    metadata = {
        "dataset": "DDInter official public download snapshot", "snapshot_date": "2026-11-14",
        "source_page": f"{DDINTER_BASE}/download/", "license_url": f"{DDINTER_BASE}/terms/",
        "license": "CC BY-NC-SA 4.0", "files": files, "aggregate_summary": summary, "combined_summary": combined,
        "cautions": [
            "Only the explicitly selected official CSV categories are included; absence is not a negative label.",
            "Absence of a drug pair does not establish clinical safety or a negative interaction label.",
            "Overlapping category files must be deduplicated by the unordered source drug identifier pair.",
            "Use as a frozen evidence resource, not an independent gold standard for a method trained on these same edges.",
        ],
    }
    if seven_category_snapshot:
        metadata.update({
            "status": "partial_fixed_seven_categories",
            "included_categories": list(categories),
            "missing_files": ["ddinter_downloads_code_R.csv"],
            "scope_reason": "Fixed A/B/D/H/L/P/V selected by network availability before evaluation; R is excluded even if downloaded later.",
        })
    save_source(folder, metadata, "source.partial.json" if seven_category_snapshot else "source.json")
    print(json.dumps({"ddinter_combined": combined}, ensure_ascii=False, indent=2), flush=True)


def fetch_dialmed():
    folder = ROOT / "data/local/dialmed"
    folder.mkdir(parents=True, exist_ok=True)
    remote_files = ["LICENSE", "README.md", "data/dataset/label.json"]
    remote_files += [f"data/dataset/{split}.txt" for split in ("train", "dev", "test")]
    remote_files += ["appendix/ddi.json", "appendix/medication_normalization.json"]
    files = [fetch(folder, Path(name).name, f"{DIALMED_BASE}/{name}") for name in remote_files]
    label_count = len(json.loads((folder / "label.json").read_text(encoding="utf-8")))
    summary = {"label_count": label_count, "splits": {}}
    for split in ("train", "dev", "test"):
        with (folder / f"{split}.txt").open(encoding="utf-8") as source:
            rows = [json.loads(line) for line in source if line.strip()]
        fields = sorted({key for row in rows for key in row})
        if not {"dialog", "label", "disease"}.issubset(fields):
            raise ValueError(f"Unexpected DialMed schema: {split}")
        summary["splits"][split] = {"rows": len(rows), "fields": fields}
    save_source(folder, {
        "dataset": "DialMed", "commit": DIALMED_COMMIT,
        "source_page": "https://github.com/f-window/DialMed",
        "license": "Author repository MIT LICENSE; retained without modification",
        "files": files, "aggregate_summary": summary,
        "cautions": [
            "Dialogue-based medication recommendation, not longitudinal hospital-visit prediction.",
            "Retain official train/dev/test files; do not feed label answers as model inputs.",
            "Check the original task's dialogue masking and diagnosed-disease input before comparing experiments.",
            "Public benchmark may have appeared in language model pretraining.",
        ],
    })
    print(json.dumps({"dialmed": summary}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("ddicorpus", "ddinter", "dialmed"), required=True)
    parser.add_argument("--seven-category-snapshot", action="store_true", help="DDInter only: fixed A/B/D/H/L/P/V snapshot, without requesting R")
    args = parser.parse_args()
    if args.seven_category_snapshot and args.dataset != "ddinter":
        parser.error("--seven-category-snapshot requires --dataset ddinter")
    if args.dataset == "ddinter":
        fetch_ddinter(args.seven_category_snapshot)
    else:
        {"ddicorpus": fetch_corpus, "dialmed": fetch_dialmed}[args.dataset]()
