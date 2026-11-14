"""One fixed, inexpensive supervised reference for the same DDICorpus pilot."""

import json
import pickle
import time
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from .evaluate_ddicorpus import ROOT, SEED, read_corpus, read_jsonl, write_jsonl, metrics


def feature_text(value):
    # Entity identity is available to both methods; no pair ID or gold type is used.
    return f"Target one: {value['entity1']['text']}. Target two: {value['entity2']['text']}. Sentence: {value['sentence']}"


def main():
    prepared = ROOT / "data/processed/knowledge/ddicorpus-pilot-v1"
    output = ROOT / "outputs/knowledge/ddicorpus-tfidf-v1"
    if output.exists():
        raise ValueError("Existing baseline is preserved; use a new version for a new experiment")
    rows = read_corpus(ROOT / "data/local/ddicorpus-2013/DDICorpus-2013.zip")
    inputs, labels = read_jsonl(prepared / "pilot-inputs.jsonl"), read_jsonl(prepared / "pilot-labels.jsonl")
    train = rows["train"]
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=40000, sublinear_tf=True),
                          LogisticRegression(C=1, solver="liblinear", class_weight="balanced", random_state=SEED, max_iter=1000))
    start = time.perf_counter()
    model.fit([feature_text(r["input"]) for r in train], [r["target"] == "interaction" for r in train])
    probabilities = model.predict_proba([feature_text(r["input"]) for r in inputs])[:, 1]
    predicted = {r["case_id"]: "interaction" if p >= .5 else "not_stated" for r, p in zip(inputs, probabilities)}
    report = {"method": "supervised TF-IDF + fixed logistic regression; not zero-shot", "seed": SEED,
              "train_pairs": len(train), "train_documents": len({r["document"] for r in train}),
              "features": len(model[0].vocabulary_), "threshold": .5, "seconds": time.perf_counter()-start,
              "parameters": {"ngram_range": [1, 2], "min_df": 2, "max_features": 40000, "sublinear_tf": True,
                             "C": 1, "solver": "liblinear", "class_weight": "balanced", "max_iter": 1000},
              "fit_iterations": model[1].n_iter_.tolist(), "metrics": metrics(labels, predicted),
              "scope": "All preprocessing fitted on official train; no test vocabulary or parameter selection. Same fixed 80-pair exploratory pilot."}
    output.mkdir(parents=True)
    with (output / "model.pkl").open("wb") as f:
        pickle.dump(model, f)
    write_jsonl(output / "responses.jsonl", [{"case_id": r["case_id"], "response": {"relation": predicted[r["case_id"]]},
                                             "score": float(p)} for r, p in zip(inputs, probabilities)])
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
