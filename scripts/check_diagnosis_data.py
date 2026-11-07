"""Read the bundled diagnosis data and print aggregate preparation statistics."""

import json
import pickle
from pathlib import Path


class DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"Global objects are not allowed: {module}.{name}")


def inspect_dataset(path):
    with path.open("rb") as source:
        data = DataOnlyUnpickler(source).load()
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a split dictionary")
    symptoms, diseases = set(), set()
    for split in ("train", "test"):
        records = data.get(split)
        if not isinstance(records, list) or not records:
            raise ValueError(f"{path}: missing or empty {split} split")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("disease_tag"), str):
                raise ValueError(f"{path}: invalid disease record")
            diseases.add(record["disease_tag"])
            goal = record.get("goal")
            if not isinstance(goal, dict):
                raise ValueError(f"{path}: invalid symptom goal")
            for key in ("explicit_inform_slots", "implicit_inform_slots"):
                slots = goal.get(key)
                if not isinstance(slots, dict):
                    raise ValueError(f"{path}: invalid {key}")
                if any(not isinstance(k, str) or not isinstance(v, bool) for k, v in slots.items()):
                    raise ValueError(f"{path}: expected named symptoms and boolean answers")
                symptoms.update(slots)
    validation = data.get("validate", [])
    if not isinstance(validation, list):
        raise ValueError(f"{path}: invalid validation split")
    return {
        "train": len(data["train"]),
        "test": len(data["test"]),
        "validation": len(validation),
        "diseases": len(diseases),
        "observed_symptoms": len(symptoms),
    }


def main():
    base = Path(__file__).resolve().parents[1] / "third_party/Diaformer/data"
    results = {
        name: inspect_dataset(base / f"{name}_dataset/goal_set.p")
        for name in ("dxy", "muzhi", "synthetic")
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
