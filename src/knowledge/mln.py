"""Exact conditional MLN for observed-positive conjunctions and one disease.

This is a restricted MLN, not an Alchemy replacement. See BIBM_DIAGNOSIS.md
for the formula-count derivation and the observation-predicate semantics.
"""

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


SCHEMA = "bibm-observed-positive-v1"


def validate_rules(document, diseases, symptoms):
    if document.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported diagnosis rule schema")
    rules = document.get("rules")
    if not isinstance(rules, list):
        raise ValueError("Rules must be a list")
    seen_ids, seen_formulas = set(), set()
    for rule in rules:
        body = rule.get("symptoms")
        if rule.get("disease") not in diseases:
            raise ValueError("Unknown disease in rule")
        if not isinstance(body, list) or not 1 <= len(body) <= 3:
            raise ValueError("Expected a conjunction of 1 to 3 observed positives")
        if len(set(body)) != len(body) or any(s not in symptoms for s in body):
            raise ValueError("Unknown or repeated symptom in rule")
        if not isinstance(rule.get("id"), str) or not rule["id"] or rule["id"] in seen_ids:
            raise ValueError("Missing or duplicate rule ID")
        if not isinstance(rule.get("source_id"), str) or not rule["source_id"]:
            raise ValueError("Each clinical association needs a source")
        formula = (rule["disease"], tuple(sorted(body)))
        if formula in seen_formulas:
            raise ValueError("Duplicate formulas must not receive duplicate weights")
        seen_ids.add(rule["id"])
        seen_formulas.add(formula)
    return rules


class ConditionalMLN:
    """Enumerate every world allowed by an exactly-one-disease hard constraint."""

    def __init__(self, diseases, symptoms, rules):
        self.diseases, self.symptoms = list(diseases), list(symptoms)
        if len(set(diseases)) != len(diseases) or not diseases:
            raise ValueError("Disease domain must be nonempty and unique")
        if len(set(symptoms)) != len(symptoms) or not symptoms:
            raise ValueError("Symptom domain must be nonempty and unique")
        self.rules = validate_rules({"schema_version": SCHEMA, "rules": rules}, diseases, symptoms)
        self.weights = np.zeros(len(diseases) + len(rules), dtype=np.float64)
        self.fit_info = None

    def activations(self, evidence):
        rows = []
        for positive in evidence:
            positive = set(positive)
            if not positive <= set(self.symptoms):
                raise ValueError("Evidence contains an unknown observation predicate")
            rows.append([set(rule["symptoms"]) <= positive for rule in self.rules])
        return np.asarray(rows, dtype=np.float64).reshape(len(evidence), len(self.rules))

    def formula_counts(self, evidence):
        """n[patient, disease-world, formula], including satisfied implications."""
        active = self.activations(evidence)
        n, k = len(evidence), len(self.diseases)
        counts = np.zeros((n, k, len(self.weights)), dtype=np.float64)
        counts[:, :, :k] = np.eye(k)[None, :, :]
        for r, rule in enumerate(self.rules):
            head = self.diseases.index(rule["disease"])
            counts[:, :, k + r] = 1.0 - active[:, r, None]
            counts[:, head, k + r] = 1.0
        return counts

    @staticmethod
    def objective(weights, counts, labels, l2):
        scores = counts @ weights
        log_z = logsumexp(scores, axis=1)
        loss = np.mean(log_z - scores[np.arange(len(labels)), labels])
        probabilities = np.exp(scores - log_z[:, None])
        expected = np.einsum("nk,nkr->nr", probabilities, counts)
        gradient = np.mean(expected - counts[np.arange(len(labels)), labels], axis=0)
        return loss + l2 * np.dot(weights, weights) / 2, gradient + l2 * weights

    def fit(self, evidence, labels, l2=0.01):
        if len(evidence) != len(labels) or not labels or l2 <= 0:
            raise ValueError("Need aligned nonempty training observations and positive L2")
        y = np.asarray([self.diseases.index(label) for label in labels])
        counts = self.formula_counts(evidence)
        result = minimize(self.objective, np.zeros_like(self.weights), args=(counts, y, l2),
                          method="L-BFGS-B", jac=True,
                          options={"maxiter": 500, "gtol": 1e-8, "ftol": 1e-12})
        self.weights = result.x
        self.fit_info = {"success": bool(result.success), "message": str(result.message),
                         "iterations": int(result.nit), "objective": float(result.fun),
                         "gradient_max_abs": float(np.max(np.abs(result.jac))),
                         "l2": l2, "initialization": "all_zero", "optimizer": "L-BFGS-B",
                         "training_cases": len(labels)}
        if not result.success or not np.all(np.isfinite(self.weights)):
            raise RuntimeError(f"MLN learning failed: {self.fit_info}")
        return self

    def predict_proba(self, evidence):
        scores = self.formula_counts(evidence) @ self.weights
        return np.exp(scores - logsumexp(scores, axis=1, keepdims=True))

    def explain(self, positive):
        active = self.activations([positive])[0]
        k = len(self.diseases)
        return {"disease_biases": dict(zip(self.diseases, self.weights[:k].tolist())),
                "active_rules": [{**{key: r[key] for key in ("id", "disease", "symptoms", "source_id")},
                                  "weight": float(self.weights[k + j])}
                                 for j, r in enumerate(self.rules) if active[j]],
                "meaning": "Log-score contributions; not clinical proof or calibrated risk"}

    def save(self, path):
        Path(path).write_text(json.dumps({"schema_version": SCHEMA, "diseases": self.diseases,
            "symptoms": self.symptoms, "rules": self.rules, "weights": self.weights.tolist(),
            "fit": self.fit_info}, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA:
            raise ValueError("Unsupported saved MLN schema")
        model = cls(value["diseases"], value["symptoms"], value["rules"])
        weights = np.asarray(value["weights"], dtype=np.float64)
        if weights.shape != model.weights.shape or not np.all(np.isfinite(weights)):
            raise ValueError("Invalid saved rule weights")
        model.weights, model.fit_info = weights, value["fit"]
        return model

    def export_mln(self, path):
        d = {name: f"D{i:02d}" for i, name in enumerate(self.diseases)}
        s = {name: f"S{i:02d}" for i, name in enumerate(self.symptoms)}
        lines = ["// Reference Alchemy syntax; executed by our exact conditional engine.",
                 "// ObservedPositive is a report, not a latent clinical symptom.",
                 "disease = {" + ", ".join(d.values()) + "}",
                 "symptom = {" + ", ".join(s.values()) + "}",
                 "ObservedPositive(symptom, patient)", "Diagnosis(disease!, patient)", ""]
        for i, name in enumerate(self.diseases):
            lines.append(f"{self.weights[i]:.17g} Diagnosis({d[name]}, p)")
        for i, rule in enumerate(self.rules, len(self.diseases)):
            body = " ^ ".join(f"ObservedPositive({s[x]}, p)" for x in rule["symptoms"])
            lines.append(f"{self.weights[i]:.17g} {body} => Diagnosis({d[rule['disease']]}, p)")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def export_evidence(self, path, evidence, labels=None):
        if labels is not None and len(labels) != len(evidence):
            raise ValueError("Labels do not align with evidence")
        self.activations(evidence)
        lines = ["// False ObservedPositive means no recorded positive; NOT symptom absent."]
        for i, positive in enumerate(evidence):
            for j, symptom in enumerate(self.symptoms):
                prefix = "" if symptom in positive else "!"
                lines.append(f"{prefix}ObservedPositive(S{j:02d}, P{i:04d})")
            if labels is not None:
                for j, disease in enumerate(self.diseases):
                    prefix = "" if disease == labels[i] else "!"
                    lines.append(f"{prefix}Diagnosis(D{j:02d}, P{i:04d})")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
