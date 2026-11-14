"""Original-product metadata and the explicitly mapped ingredient/CID DDI graph."""

from collections import Counter, defaultdict
import csv

import numpy as np


def product_catalog(snapshot, codes):
    if snapshot.get("schema_version") != "rxnorm-products-v1":
        raise ValueError("Unsupported RxNorm product snapshot")
    catalog = {}
    for code in codes:
        history = snapshot["drugs"][code]["rxcuiStatusHistory"]
        attributes = history["attributes"]
        if attributes["rxcui"] != code:
            raise ValueError("Product snapshot identifier mismatch")
        features = history.get("definitionalFeatures", {})
        catalog[code] = {
            "system": "RxNorm", "code": code, "name": attributes.get("name"),
            "term_type": attributes.get("tty"), "status": history["metaData"]["status"],
            "is_multiple_ingredient": attributes.get("isMultipleIngredient"),
            "ingredient_and_strength": features.get("ingredientAndStrength", []),
            "dose_forms": features.get("doseFormConcept", []),
            "dose_form_groups": features.get("doseFormGroupConcept", []),
            "pack": history.get("pack", {}), "derived_concepts": history.get("derivedConcepts", {}),
            "identity_policy": "Preserve original RxCUI; no active replacement, ingredient or brand merging",
        }
    return catalog


def outside_input_codes(case, indices):
    """Audit A1 input tokens without using current medication targets."""
    issues = []
    visits = [("", case, ("diagnoses", "procedures"))]
    visits += [(f"history[{i}].", visit, ("diagnoses", "procedures", "medications"))
               for i, visit in enumerate(case["history"])]
    for prefix, visit, fields in visits:
        for field in fields:
            for item in visit[field]:
                key = item["code"] if field == "medications" else item["system"] + "|" + item["code"]
                if key not in indices[field]:
                    issues.append({"field": prefix + field, **item})
    return issues


def ddi_graph(reference, medications, least_frequent, bridge):
    """Only complete, uniquely grounded products enter the graph and pair mask.

    Positive observations involving partial products are counted separately; they
    cannot enter a numerator whose denominator includes only complete pairs.
    """
    drug_cids, complete = bridge["drug_cids"], bridge["mapping_complete"]
    cid_codes = defaultdict(set)
    audit_cid_codes = defaultdict(set)
    mapped = np.zeros(len(medications), dtype=np.float32)
    for code, index in medications.items():
        cids = drug_cids.get(code, [])
        if type(complete.get(code)) is not bool or not isinstance(cids, list):
            raise ValueError(f"Missing explicit CID mapping status: {code}")
        if complete[code] and not cids:
            raise ValueError("A complete product must have at least one ingredient CID")
        if len(cids) != len(set(cids)) or any(not isinstance(cid, str) or not cid.startswith("CID") for cid in cids):
            raise ValueError("CID mapping must contain unique source CID strings")
        mapped[index] = complete[code]
        for cid in cids:
            if complete[code]:
                cid_codes[cid].add(index)
        partial = bridge.get("partial_drug_cids", {}).get(code, cids)
        if not isinstance(partial, list) or any(not isinstance(cid, str) or not cid.startswith("CID") for cid in partial):
            raise ValueError("Partial CID audit must contain source CID strings")
        for cid in set(cids) | set(partial):
            audit_cid_codes[cid].add(index)
    mask = np.outer(mapped, mapped)
    np.fill_diagonal(mask, 0)
    counts = Counter()
    with (reference / "drug-DDI.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            counts[(row["Polypharmacy Side Effect"], row["Side Effect Name"])] += 1
    chosen = sorted(counts, key=lambda key: (counts[key], key))[:least_frequent]
    event_names = {name for _, name in chosen}
    graph = np.zeros_like(mask)
    partial_edges, partial_rows, selected_rows = set(), 0, 0
    with (reference / "drug-DDI.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row["Side Effect Name"] not in event_names:
                continue
            selected_rows += 1
            partial = False
            for i in cid_codes.get(row["STITCH 1"], ()):
                for j in cid_codes.get(row["STITCH 2"], ()):
                    if i == j:
                        continue
                    graph[i, j] = graph[j, i] = 1
            for i in audit_cid_codes.get(row["STITCH 1"], ()):
                for j in audit_cid_codes.get(row["STITCH 2"], ()):
                    if i != j and not mask[i, j]:
                        partial_edges.add(tuple(sorted((i, j))))
                        partial = True
            partial_rows += partial
    return graph, mask, {
        "policy": "Same least-frequent event/name selection; only completely mapped original RxCUI pairs",
        "event_groups": len(chosen), "selected_events": chosen, "source_rows": sum(counts.values()),
        "selected_source_rows": selected_rows, "undirected_edges": int(graph.sum() / 2),
        "complete_products": int(mapped.sum()), "product_count": len(medications),
        "incomplete_products": [code for code, index in medications.items() if not mapped[index]],
        "partial_positive_edges_excluded": len(partial_edges), "partial_positive_source_rows": partial_rows,
        "rate_scope": "Pairs where every ingredient of both products has a unique source CID; unmarked is not clinically safe",
        "bridge_policy": bridge.get("policy_version"), "bridge_method": bridge.get("method"),
    }
