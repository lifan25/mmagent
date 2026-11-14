"""Snapshot public drug terminology only; never send patient records to RxNav."""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from prepare import ROOT, read_jsonl

BASE = "https://rxnav.nlm.nih.gov/REST/"
OUTPUT = Path(__file__).parent / "resources/rxclass-synthea.json"


def get(path):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(BASE + path, timeout=30) as response:
                return json.load(response)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def fetch(code):
    responses = {}
    for source in ("ATCPROD", "ATC"):
        responses[source] = get(f"rxclass/class/byRxcui.json?rxcui={code}&relaSource={source}")
    return code, responses


if __name__ == "__main__":
    if OUTPUT.exists():
        raise SystemExit("Snapshot exists; preserve it and use a new version for refreshes")
    visits = read_jsonl(ROOT / "data/processed/data_evaluation/synthea-apr2020-v3/main_visits.jsonl")
    codes = sorted({item["code"] for visit in visits for item in visit["medications"]})
    versions = {source: get(f"rxclass/version/{source}.json")
                for source in ("ATCPROD", "ATC")}
    with ThreadPoolExecutor(max_workers=4) as pool:
        drugs = dict(pool.map(fetch, codes))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"retrieved_at": datetime.now(timezone.utc).isoformat(),
                                  "base_url": BASE, "versions": versions, "drugs": drugs}, indent=2),
                      encoding="utf-8")
    print(f"Saved {len(drugs)} standard drug identifiers to {OUTPUT}")
