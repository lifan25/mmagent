"""Join complete RxNorm base-ingredient sets to a fixed reference via exact ATC5.

Only drug terminology is requested. A unique join is not independent chemical
identity validation, clinical interaction coverage, or evidence of safety.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
ATC5 = re.compile(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}\Z")
PRODUCTS = ROOT / "src/recommendation/resources/rxnorm-products-synthea-v1.json"
REFERENCE = ROOT / "data/reference/MoleRec/drug-atc.csv"
CACHE = ROOT / "outputs/recommendation/rxnorm-cid-v1"
EXISTING = ROOT / "outputs/data_evaluation/rxnorm-design-20261114"
OUTPUT = ROOT / "src/recommendation/resources/rxnorm-cid-v1.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reference_index(path):
    index = defaultdict(set)
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            if not row or not re.fullmatch(r"CID[0-9]+", row[0]):
                raise ValueError("Malformed source CID; do not normalize or strip its prefix")
            for code in row[1:]:
                if not ATC5.fullmatch(code):
                    raise ValueError("Reference includes a non-ATC5 code")
                index[code].add(row[0])
    return index


def product_components(code, response):
    history = response.get("rxcuiStatusHistory", {})
    attributes = history.get("attributes", {})
    rows = history.get("definitionalFeatures", {}).get("ingredientAndStrength", [])
    problems = []
    if attributes.get("rxcui") != code:
        problems.append("response_product_identifier_mismatch")
    if history.get("metaData", {}).get("status") not in {"Active", "Obsolete"}:
        problems.append("unsupported_or_remapped_product_status")
    if not rows or any(not str(row.get("baseRxcui", "")).isdigit() for row in rows):
        problems.append("missing_base_ingredient")
    base = sorted({row["baseRxcui"] for row in rows if str(row.get("baseRxcui", "")).isdigit()})
    declared = attributes.get("isMultipleIngredient")
    if declared not in {"YES", "NO"} or (declared == "YES") != (len(base) > 1):
        problems.append("inconsistent_declared_ingredient_count")
    derived = sorted({row.get("ingredientRxcui") for row in
                      history.get("derivedConcepts", {}).get("ingredientConcept", [])
                      if row.get("ingredientRxcui")})
    if derived and derived != base:
        problems.append("base_and_derived_ingredient_sets_disagree")
    return {"rxcui": code, "name": attributes.get("name"), "tty": attributes.get("tty"),
            "rxnorm_status": history.get("metaData", {}).get("status"),
            "is_multiple_ingredient": declared, "base_rxcuis": base,
            "ingredient_and_strength": rows, "derived_ingredient_rxcuis": derived,
            "component_list_complete": not problems, "component_list_issues": problems}


def ingredient_join(response, index):
    properties = (response.get("propConceptGroup") or {}).get("propConcept", [])
    raw_codes = sorted({str(row["propValue"]) for row in properties if row.get("propName") == "ATC"})
    atc = [code for code in raw_codes if ATC5.fullmatch(code)]
    matches = {code: sorted(index.get(code, set())) for code in atc}
    cids = sorted({cid for values in matches.values() for cid in values})
    complete = len(cids) == 1
    status = "unique_in_fixed_reference" if complete else "multiple_cid_candidates" if cids else "no_cid_join"
    return {"atc5": atc, "non_atc5_properties": [code for code in raw_codes if code not in atc],
            "atc5_cid_matches": matches, "unmatched_atc5": [code for code in atc if not matches[code]],
            "cid_candidates": cids, "mapping_complete": complete, "status": status}


def product_join(product, ingredients):
    missing = [code for code in product["base_rxcuis"] if not ingredients[code]["mapping_complete"]]
    complete = product["component_list_complete"] and bool(product["base_rxcuis"]) and not missing
    candidates = sorted({cid for code in product["base_rxcuis"] for cid in ingredients[code]["cid_candidates"]})
    partial = sorted({cid for code in product["base_rxcuis"] if ingredients[code]["mapping_complete"]
                      for cid in ingredients[code]["cid_candidates"]})
    # Incomplete products expose candidate sets only in audit, never as usable drug_cids.
    return {**product, "mapping_complete": complete, "incomplete_ingredients": missing,
            "all_candidate_cids": candidates, "drug_cids": candidates if complete else [],
            "partial_drug_cids": partial}


def fetch_properties(code, cache, offline):
    cache.mkdir(parents=True, exist_ok=True)
    path, metadata = cache / f"ingredient-{code}-codes.json", cache / f"ingredient-{code}-codes.source.json"
    url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{code}/allProperties.json?prop=codes"
    if path.exists() and metadata.exists():
        info = read_json(metadata)
        if info["sha256"] != digest(path) or info["url"] != url:
            raise ValueError("Ingredient cache and source metadata disagree")
        return read_json(path), info
    earlier = EXISTING / path.name
    if earlier.exists():
        path.write_bytes(earlier.read_bytes())
        info = {"url": url, "retrieved_at": None, "cache_origin": earlier.relative_to(ROOT).as_posix(),
                "note": "Reused preexisting source response; its original retrieval time was not recorded"}
    else:
        if offline:
            raise FileNotFoundError(f"No cached terminology for ingredient {code}")
        for attempt in range(2):
            try:
                request = Request(url, headers={"User-Agent": "mmagent-research-terminology/1.0"})
                with urlopen(request, timeout=30) as response:
                    content = response.read()
                json.loads(content)
                path.write_bytes(content)
                info = {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "cache_origin": "official_NLM_RxNorm_API"}
                break
            except (OSError, ValueError):
                if attempt == 1:
                    raise
                time.sleep(1)
    info.update(sha256=digest(path), cache_file=path.relative_to(ROOT).as_posix())
    save_json(metadata, info)
    return read_json(path), info


def self_check():
    def response(*codes):
        return {"propConceptGroup": {"propConcept": [{"propName": "ATC", "propValue": c} for c in codes]}}
    index = {"A10BA02": {"CID000004091"}, "M01AE01": {"CID000003672"},
             "B01AA03": {"CID000006691", "CID000099999"}}
    metformin = ingredient_join(response("A10BA02"), index)
    ibuprofen = ingredient_join(response("M01AE01", "R02AX02"), index)
    ambiguous = ingredient_join(response("B01AA03"), index)
    assert ibuprofen["mapping_complete"] and ibuprofen["unmatched_atc5"] == ["R02AX02"]
    assert not ambiguous["mapping_complete"] and len(ambiguous["cid_candidates"]) == 2
    assert not ingredient_join(response("A10B"), index)["mapping_complete"]
    product = {"component_list_complete": True, "base_rxcuis": ["a", "b"]}
    incomplete = product_join(product, {"a": metformin, "b": ambiguous})
    assert not incomplete["drug_cids"] and incomplete["partial_drug_cids"] == ["CID000004091"]
    joined = product_join(product, {"a": metformin, "b": ibuprofen})
    assert joined["mapping_complete"] and len(joined["drug_cids"]) == 2


def build(products_path, reference_path, cache, output, offline):
    self_check()
    source = read_json(products_path)
    if source.get("schema_version") != "rxnorm-products-v1":
        raise ValueError("Unexpected product snapshot schema")
    products = {code: product_components(code, response) for code, response in source["drugs"].items()}
    codes = sorted({code for product in products.values() for code in product["base_rxcuis"]})
    index = reference_index(reference_path)
    ingredients, failures = {}, {}

    def fetch_one(code):
        try:
            response, provenance = fetch_properties(code, cache, offline)
            return code, {**ingredient_join(response, index), "source": provenance}
        except (OSError, ValueError) as error:
            return code, {"mapping_complete": False, "status": "source_fetch_or_cache_error",
                          "cid_candidates": [], "error": f"{type(error).__name__}: {error}"}

    with ThreadPoolExecutor(max_workers=2) as workers:
        for number, (code, result) in enumerate(workers.map(fetch_one, codes), 1):
            ingredients[code] = result
            if "error" in result:
                failures[code] = result["error"]
            if number % 10 == 0 or number == len(codes):
                print(json.dumps({"ingredients_checked": number, "total": len(codes), "source_failures": len(failures)}), flush=True)
    audited = {code: product_join(product, ingredients) for code, product in products.items()}
    stats = {"products": len(products), "unique_base_ingredients": len(ingredients),
             "complete_products": sum(p["mapping_complete"] for p in audited.values()),
             "complete_ingredients": sum(p["mapping_complete"] for p in ingredients.values()),
             "multicomponent_products": sum(len(p["base_rxcuis"]) > 1 for p in audited.values()),
             "complete_multicomponent_products": sum(p["mapping_complete"] and len(p["base_rxcuis"]) > 1 for p in audited.values()),
             "ingredient_statuses": dict(Counter(p["status"] for p in ingredients.values())),
             "source_fetch_failures": len(failures),
             "reference_atc5_codes": len(index), "ambiguous_reference_atc5": sum(len(v) > 1 for v in index.values())}
    bridge = {"schema_version": "rxnorm-cid-v1", "policy_version": "complete-bases-union-unique-atc5-20261114",
              "products_source": {"path": products_path.relative_to(ROOT).as_posix(), "sha256": digest(products_path),
                                  "rxnorm_version": source.get("version")},
              "reference_source": {"path": reference_path.relative_to(ROOT).as_posix(), "sha256": digest(reference_path)},
              "method": "All baseRxcui components; official ATC properties restricted to seven-character ATC5; exact reference join. Each component needs at least one match and exactly one CID across all matched ATC5 codes; every product component must qualify.",
              "scope": "Uniquely connected CID in this fixed reference, not independent chemical identity validation or complete DDI evidence coverage. Missing ATC5 branches are audited, not treated as alternative identity evidence. No ATC3 reverse inference.",
              "api_documentation": ["https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getAllProperties.html",
                                    "https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRxcuiHistoryStatus.html"],
              "drug_cids": {code: p["drug_cids"] for code, p in audited.items()},
              "partial_drug_cids": {code: p["partial_drug_cids"] for code, p in audited.items()},
              "mapping_complete": {code: p["mapping_complete"] for code, p in audited.items()},
              "products": audited, "ingredients": ingredients, "statistics": stats,
              "status": "complete_source_collection" if not failures else "partial_source_collection"}
    if output.exists():
        if read_json(output) != bridge:
            raise ValueError("Existing bridge differs; preserve it and select a new output version")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        save_json(output, bridge)
    print(json.dumps(stats), flush=True)
    return bridge


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, default=PRODUCTS)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--cache-dir", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--offline", action="store_true", help="Rebuild solely from already cached official responses")
    args = parser.parse_args()
    build(args.products.resolve(), args.reference.resolve(), args.cache_dir.resolve(), args.output.resolve(), args.offline)
