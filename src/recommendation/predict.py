"""Strict 0.1-draft Case interface for the existing, frozen SSPNet checkpoint."""

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from .model import ROOT, SSPNetAdapter
from .prepare import token

CONTRACT_VERSION = "0.1-draft"
DEFAULT_CHECKPOINT = ROOT / "outputs/recommendation/sspnet-synthea-v3-product-cpu-seed8/best.pt"
CASE_FIELDS = {"contract_version", "data_kind", "case_id", "diagnoses", "procedures", "history", "context"}
VISIT_FIELDS = {"visit_index", "diagnoses", "procedures", "medications"}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SSPNetRecommender:
    """Load once, then call score_case or recommend repeatedly; no patient-result cache.

    CPU defaults to one PyTorch thread, matching the saved run. This changes the
    process-wide PyTorch thread setting. Constructor failures are configuration
    errors and raise; invalid Cases return a non-ok Recommendation without inference.
    """

    def __init__(self, checkpoint_path=None, prepared_dir=None, device="cpu", num_threads=1):
        self.checkpoint_path = Path(checkpoint_path or DEFAULT_CHECKPOINT).resolve()
        self.device = torch.device(device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("Configured CUDA is unavailable; select CPU explicitly")
        checkpoint = torch.load(self.checkpoint_path, map_location=self.device, weights_only=True)
        self.config = dict(checkpoint["config"])
        self.prepared_dir = Path(prepared_dir or ROOT / self.config["prepared_dir"]).resolve()
        paths = {name: self.prepared_dir / filename for name, filename in {
            "vocabulary": "vocabulary.json", "graphs": "graphs.npz",
            "mapping": "mapping-decisions.json", "preparation": "manifest.json",
        }.items()}
        self.vocabulary = json.loads(paths["vocabulary"].read_text(encoding="utf-8"))
        if checkpoint["vocabulary"] != self.vocabulary:
            raise ValueError("Checkpoint vocabulary differs from prepared vocabulary (including order)")
        self.indices = {field: {value: i for i, value in enumerate(values)}
                        for field, values in self.vocabulary.items()}
        if any(len(self.indices[k]) != len(v) for k, v in self.vocabulary.items()):
            raise ValueError("Duplicate entries in model vocabulary")
        self.medication_codes = list(self.vocabulary["medications"])
        self.mapping = json.loads(paths["mapping"].read_text(encoding="utf-8"))
        preparation = json.loads(paths["preparation"].read_text(encoding="utf-8"))
        sizes = tuple(len(self.vocabulary[k]) for k in ("diagnoses", "procedures", "medications"))
        with np.load(paths["graphs"], allow_pickle=False) as graph:
            ehr, ddi = graph["ehr"].copy(), graph["ddi"].copy()
        for name, matrix in (("ehr", ehr), ("ddi", ddi)):
            if (matrix.shape != (sizes[2], sizes[2]) or not np.isfinite(matrix).all()
                    or not np.array_equal(matrix, matrix.T) or np.any(np.diag(matrix))):
                raise ValueError(f"Invalid or incompatible {name} graph")
        state = checkpoint["state_dict"]
        if not torch.equal(state["ddi_tensor"].cpu(), torch.as_tensor(ddi)):
            raise ValueError("DDI graph differs from the checkpoint buffer")
        if not torch.equal(state["med_ids"].cpu(), torch.arange(sizes[2])):
            raise ValueError("Checkpoint medication indices differ from vocabulary order")
        self.threshold = float(self.config["threshold"])
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("Invalid checkpoint threshold")
        if num_threads is not None:
            torch.set_num_threads(num_threads)
        # Constructing the module must not consume the caller's CPU random stream.
        with torch.random.fork_rng(devices=[]):
            self.model = SSPNetAdapter(self.config, sizes, ehr, ddi, self.device)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        paths.update(checkpoint=self.checkpoint_path, adapter=Path(__file__).with_name("model.py"),
                     interface=Path(__file__), upstream=ROOT / "third_party/SSPNet/src/modules/MoleRec.py")
        hashes = {name: file_sha256(path) for name, path in paths.items()}
        identity = json.dumps({"hashes": hashes, "threshold": self.threshold,
                               "device": str(self.device), "torch": torch.__version__}, sort_keys=True)
        self.model_version = "sspnet-case-v1-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        self.manifest = {
            "model_version": self.model_version, "contract_version": CONTRACT_VERSION,
            "checkpoint_epoch": checkpoint["epoch"], "threshold": self.threshold,
            "drug_system": "ATC3", "drug_level": 3, "medication_codes": self.medication_codes,
            "vocabulary_sizes": dict(zip(("diagnoses", "procedures", "medications"), sizes)),
            "files": {k: str(p) for k, p in paths.items()}, "sha256": hashes,
            "source_a1": preparation.get("source_a1"), "mapping": preparation.get("mapping"),
            "device": str(self.device), "torch": torch.__version__,
            "torch_threads": torch.get_num_threads(),
            "unknown_policy": "reject; no implicit UNK or medication dropping",
            "context_policy": "context is preserved by the caller but is not an SSPNet model input",
        }

    def _encode_case(self, case):
        issues, missing = [], False

        def issue(code, field, message, needs_information=False):
            nonlocal missing
            missing |= needs_information
            issues.append({"code": code, "field": field, "message": message})

        def codes(items, field, vocabulary_field):
            if items is None:
                issue("missing_information", field, "Code list is unknown; null is not an empty set", True)
                return []
            if not isinstance(items, list):
                issue("invalid_type", field, "Expected a list of system/code objects")
                return []
            encoded = set()
            for i, item in enumerate(items):
                location = f"{field}[{i}]"
                if (not isinstance(item, dict) or set(item) != {"system", "code"}
                        or any(not isinstance(item.get(k), str) or not item[k]
                               or item[k] != item[k].strip() for k in ("system", "code"))):
                    issue("invalid_code", location, "Require exactly nonempty string system/code; do not coerce identifiers")
                    continue
                key = token(item)
                if vocabulary_field == "medications":
                    if item["system"] == "ATC3":
                        options = [item["code"]]
                    elif item["system"] == "RxNorm":
                        options = self.mapping.get(item["code"], {}).get("classes", [])
                    else:
                        options = []
                    if len(options) != 1 or options[0] not in self.indices["medications"]:
                        issue("unsupported_code", location, f"{key}: no unique mapping inside this model's ATC3 vocabulary")
                        continue
                    key = options[0]
                if key not in self.indices[vocabulary_field] or key == "<UNK>":
                    issue("unsupported_code", location, f"{key}: outside the fixed {vocabulary_field} vocabulary")
                else:
                    encoded.add(self.indices[vocabulary_field][key])
            return sorted(encoded)

        if not isinstance(case, dict):
            return None, "unsupported_input", [{"code": "invalid_type", "field": "case", "message": "Expected a Case object"}]
        for field in sorted(CASE_FIELDS - case.keys()):
            issue("missing_field", field, "Required Case field is absent", True)
        for field in sorted(case.keys() - CASE_FIELDS):
            code = "current_target_present" if field in {"medications", "target_medications", "target"} else "unexpected_field"
            issue(code, field, "Not a Case input field; keep current medication answers in evaluation data")
        if "contract_version" in case and case["contract_version"] != CONTRACT_VERSION:
            issue("unsupported_version", "contract_version", f"Expected {CONTRACT_VERSION}")
        if "data_kind" in case and case["data_kind"] not in ("synthetic", "restricted"):
            issue("invalid_value", "data_kind", "Expected synthetic or restricted")
        if "case_id" in case and (not isinstance(case["case_id"], str) or not case["case_id"].strip()):
            issue("invalid_value", "case_id", "Expected a nonempty case identifier")
        if "context" in case and not isinstance(case["context"], dict):
            issue("invalid_type", "context", "Expected an object; its individual facts may be unknown")
        current_d = codes(case.get("diagnoses"), "diagnoses", "diagnoses")
        current_p = codes(case.get("procedures"), "procedures", "procedures")
        if case.get("diagnoses") == []:
            issue("missing_diagnoses", "diagnoses", "At least one confirmed diagnosis is required", True)
        history = case.get("history")
        encoded_history = []
        if history is None:
            issue("missing_history", "history", "Historical visits have not been obtained", True)
        elif not isinstance(history, list):
            issue("invalid_type", "history", "Expected a visit list")
        elif not history:
            issue("history_required", "history", "This checkpoint requires at least one completed prior visit")
        else:
            previous_index = -1
            for i, visit in enumerate(history):
                field = f"history[{i}]"
                if not isinstance(visit, dict):
                    issue("invalid_type", field, "Expected a historical visit object")
                    continue
                for name in sorted(VISIT_FIELDS - visit.keys()):
                    issue("missing_field", f"{field}.{name}", "Required history field is absent", True)
                for name in sorted(visit.keys() - VISIT_FIELDS):
                    issue("unexpected_field", f"{field}.{name}", "Not a history contract field")
                index = visit.get("visit_index")
                if type(index) is not int or index < 0 or index <= previous_index:
                    issue("invalid_visit_order", f"{field}.visit_index", "Visit indices must be nonnegative integers in strictly increasing order")
                else:
                    previous_index = index
                encoded_history.append([codes(visit.get(name), f"{field}.{name}", name)
                                        for name in ("diagnoses", "procedures", "medications")])
                if visit.get("diagnoses") == []:
                    issue("unsupported_history", f"{field}.diagnoses", "This cohort requires diagnoses in retained historical visits")
            if encoded_history and not any(v[2] for v in encoded_history) and not issues:
                issue("no_medication_history", "history", "No observed supported medication history for this checkpoint")
        if issues:
            information_codes = {"missing_field", "missing_information", "missing_history", "missing_diagnoses"}
            status = "needs_information" if missing and all(i["code"] in information_codes for i in issues) else "unsupported_input"
            return None, status, issues
        return encoded_history + [[current_d, current_p, []]], "ok", []

    def score_case(self, case):
        """Return one inference plus its Recommendation and local evaluation data."""
        encoded, status, issues = self._encode_case(case)
        fields = case if isinstance(case, dict) else {}
        recommendation = {"contract_version": fields.get("contract_version", CONTRACT_VERSION),
                          "data_kind": fields.get("data_kind"), "case_id": fields.get("case_id"),
                          "status": status, "input_issues": issues, "model_version": self.model_version,
                          "execution": "model_inference", "candidates": []}
        result = {"recommendation": recommendation, "full_scores": None,
                  "medication_codes": list(self.medication_codes), "threshold": self.threshold,
                  "encoded_input": encoded}
        if status != "ok":
            return result
        try:
            with torch.inference_mode():
                logits, ddi_penalty = self.model(encoded)
                if not torch.isfinite(logits).all() or not torch.isfinite(ddi_penalty):
                    raise FloatingPointError("Nonfinite SSPNet inference output")
                scores = torch.sigmoid(logits).cpu().numpy()[0]
            result["full_scores"] = scores.tolist()
            recommendation["candidates"] = [
                {"drug": {"system": "ATC3", "code": code}, "score": float(score)}
                for code, score in zip(self.medication_codes, scores) if score >= self.threshold]
        except (RuntimeError, FloatingPointError) as error:
            recommendation["status"] = "error"
            recommendation["input_issues"] = [{"code": "inference_error", "field": "model", "message": str(error)}]
        return result

    def recommend(self, case):
        return self.score_case(case)["recommendation"]


@lru_cache(maxsize=1)
def get_default_recommender():
    return SSPNetRecommender()


def recommend(case):
    """Convenience entry; caches loaded artifacts, never caches by case_id."""
    return get_default_recommender().recommend(case)
