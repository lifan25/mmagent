"""Freeze public RxNorm product definitions; no patient records leave this machine."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

from .prepare import ROOT, read_jsonl

BASE = "https://rxnav.nlm.nih.gov/REST/"
DEFAULT_OUTPUT = ROOT / "src/recommendation/resources/rxnorm-products-synthea-v1.json"


def get_json(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                content = response.read()
            return json.loads(content), hashlib.sha256(content).hexdigest()
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)


def fetch(output, a1_dir, cache_dir, reuse_dir):
    if output.exists():
        raise ValueError("Snapshot exists; preserve it and select a new version")
    visits = read_jsonl(a1_dir / "main_visits.jsonl")
    codes = sorted({m["code"] for v in visits for m in v["medications"]})
    if any(m["system"] != "RxNorm" or not m["code"].isdigit() for v in visits for m in v["medications"]):
        raise ValueError("Only standard numeric RxNorm identifiers can be queried")
    version, _ = get_json(BASE + "version.json")
    cache_dir.mkdir(parents=True, exist_ok=True)
    reuse = {}
    if reuse_dir and (reuse_dir / "source.json").exists():
        old_version = json.loads((reuse_dir / "rxnorm-version.json").read_text(encoding="utf-8"))
        if old_version == version:
            source = json.loads((reuse_dir / "source.json").read_text(encoding="utf-8"))
            reuse = {r["file"]: {**r, "retrieved_at": source["retrieved_utc"]} for r in source["requests"]}

    def one(code):
        url = BASE + f"rxcui/{code}/historystatus.json"
        path = cache_dir / f"{code}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["version"] != version or record["url"] != url:
                raise ValueError("Cached terminology version differs; choose a new cache directory")
        else:
            old = reuse.get(f"{code}-history.json")
            if old:
                content = (reuse_dir / old["file"]).read_bytes()
                checksum = hashlib.sha256(content).hexdigest()
                if checksum != old["sha256"] or old["url"] != url:
                    raise ValueError("Reused response does not match its source record")
                response, retrieved = json.loads(content), old["retrieved_at"]
                origin = str(reuse_dir / old["file"])
            else:
                response, checksum = get_json(url)
                retrieved = datetime.now(timezone.utc).isoformat()
                origin = None
            record = {"url": url, "retrieved_at": retrieved, "sha256": checksum,
                      "version": version, "cache_origin": origin, "response": response}
            with path.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
        actual = record["response"].get("rxcuiStatusHistory", {}).get("attributes", {}).get("rxcui")
        if actual != code:
            raise ValueError(f"History response identifier mismatch: {code} / {actual}")
        return code, record

    responses = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(one, code) for code in codes]
        for future in as_completed(futures):
            code, record = future.result()
            responses[code] = record
            if len(responses) % 10 == 0 or len(responses) == len(codes):
                print(json.dumps({"downloaded": len(responses), "total": len(codes)}), flush=True)
    final_version, _ = get_json(BASE + "version.json")
    if final_version != version:
        raise ValueError("RxNorm changed during download; do not mix releases")
    value = {"schema_version": "rxnorm-products-v1", "retrieved_at": datetime.now(timezone.utc).isoformat(),
             "version": version, "scope": "Original product IDs, no brand/ingredient remapping and no patient records",
             "drugs": {code: responses[code]["response"] for code in codes},
             "requests": [{"rxcui": code, **{k: v for k, v in responses[code].items()
                                            if k not in {"response", "version"}}} for code in codes]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "products": len(codes), "version": version}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--a1-dir", type=Path, default=ROOT / "data/processed/data_evaluation/synthea-apr2020-v3")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "outputs/recommendation/rxnorm-metadata-download-v1")
    parser.add_argument("--reuse-dir", type=Path, default=ROOT / "outputs/knowledge/rxnorm-feasibility-20261114")
    args = parser.parse_args()
    fetch(args.output, args.a1_dir, args.cache_dir, args.reuse_dir)
