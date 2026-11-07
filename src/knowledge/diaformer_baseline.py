"""Train the original Diaformer model with a held-out validation split."""

import argparse
from collections import defaultdict
import importlib.util
import json
import logging
from pathlib import Path
import platform
import random
import subprocess
import sys
import time

import numpy as np
import torch
from torch.utils.data import DataLoader


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "third_party/Diaformer"


def load_upstream():
    sys.path.insert(0, str(UPSTREAM))
    spec = importlib.util.spec_from_file_location("_diaformer_upstream", UPSTREAM / "Diaformer.py")
    module = importlib.util.module_from_spec(spec)
    source = (UPSTREAM / "Diaformer.py").read_text(encoding="utf-8")
    unused_import = "from torch._C import DeviceObjType"
    if source.count(unused_import) != 1:
        raise RuntimeError("Review the upstream compatibility adapter for this source version")
    # The unused internal PyTorch type was removed in modern PyTorch.
    source = source.replace(unused_import, "")
    # Windows defaults to cp936; keep the local prediction JSON portable.
    source = source.replace(
        "with open(args.result_output_path,'w') as f:",
        "with open(args.result_output_path,'w', encoding='utf-8') as f:",
    )
    exec(compile(source, str(UPSTREAM / "Diaformer.py"), "exec"), module.__dict__)
    module.logger = logging.getLogger("diaformer_upstream")
    module.logger.setLevel(logging.WARNING)
    module.tqdm = lambda iterable, *args, **kwargs: iterable
    return module


def split_training(records, seed, validation_fraction=0.2):
    grouped = defaultdict(list)
    for index, record in enumerate(records):
        grouped[record["disease_tag"]].append(index)
    generator = random.Random(seed)
    validation_indices = []
    for disease in sorted(grouped):
        indices = grouped[disease]
        if len(indices) < 2:
            raise ValueError("Every class needs at least two training cases")
        generator.shuffle(indices)
        count = max(1, min(len(indices) - 1, int(len(indices) * validation_fraction + 0.5)))
        validation_indices.extend(indices[:count])
    validation_set = set(validation_indices)
    training_indices = [index for index in range(len(records)) if index not in validation_set]
    validation_indices.sort()
    return training_indices, validation_indices


def tokenize(records, tokenizer):
    tokenized = []
    for record in records:
        groups = []
        for name in ("explicit_inform_slots", "implicit_inform_slots"):
            tokens = []
            for symptom, answer in record["goal"][name].items():
                if answer == "UNK":
                    continue
                if symptom not in tokenizer.vocab:
                    raise ValueError("The dataset contains a symptom missing from its vocabulary")
                token = tokenizer.convert_token_to_id(symptom)
                tokens.append(token if answer else tokenizer.symptom_to_false[token])
            groups.append(tokens)
        if not any(groups):
            continue
        label = tokenizer.convert_disease_to_label(record["disease_tag"])
        tokenized.append(" ".join(map(str, groups[0])) + "\t" + " ".join(map(str, groups[1])) + "\t" + str(label))
    return tokenized


def prediction_metrics(predictions):
    correct = hits = available = queries = 0
    for prediction in predictions:
        correct += prediction["pred_disease"] == prediction["target_disease"]
        explicit = prediction["explicit_symptoms"]
        eligible = [name for name, value in prediction["implicit_symptoms"].items() if value != "UNK"]
        if not any(value != "UNK" for value in explicit.values()) and eligible:
            eligible = eligible[1:]
        inquiries = prediction["inquiry_symptom"]
        available += len(eligible)
        queries += len(inquiries)
        hits += sum(name in eligible for name in inquiries)
    count = len(predictions)
    if not count:
        raise ValueError("Evaluation returned no cases")
    accuracy = correct / count
    recall = hits / available if available else 0.0
    precision = hits / queries if queries else 0.0
    f1 = 2 * hits / (available + queries) if available + queries else 0.0
    return {
        "cases": count, "correct_cases": correct, "diagnosis_accuracy": accuracy,
        "symptom_recall": recall, "symptom_precision": precision, "symptom_f1": f1,
        "mean_turns": queries / count, "symptom_hits": hits,
        "available_implicit_symptoms": available, "total_queries": queries,
        "selection_score": 0.8 * accuracy + 0.2 * f1,
    }


def evaluate(module, model, device, records, path):
    module.testdata = records
    module.max_score = -1.0
    module.args.result_output_path = str(path)
    model.eval()
    with torch.inference_mode():
        module.generate(model, device, module.tokenizer, module.args)
    return prediction_metrics(json.loads(path.read_text(encoding="utf-8")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--seed", type=int, default=8)
    parser.add_argument("--eval-every", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/dxy-diaformer-seed8")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--smoke", action="store_true", help="Two training batches; validation only")
    options = parser.parse_args()
    if options.epochs < 1 or options.eval_every < 1:
        parser.error("epochs and eval-every must be positive")
    output = options.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        parser.error("Store run artifacts inside this project's ignored outputs directory")
    output.mkdir(parents=True, exist_ok=False)
    if options.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    use_cuda = torch.cuda.is_available() and options.device != "cpu"
    device = torch.device("cuda" if use_cuda else "cpu")
    torch.set_num_threads(8)
    torch.manual_seed(options.seed)
    random.seed(options.seed)
    np.random.seed(options.seed)
    if use_cuda:
        torch.cuda.manual_seed_all(options.seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    module = load_upstream()
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_diagnosis_data import DataOnlyUnpickler
    with (UPSTREAM / "data/dxy_dataset/goal_set.p").open("rb") as source:
        data = DataOnlyUnpickler(source).load()
    training_indices, validation_indices = split_training(data["train"], options.seed)
    training = [data["train"][index] for index in training_indices]
    validation = [data["train"][index] for index in validation_indices]
    epochs = 1 if options.smoke else options.epochs
    module.args = argparse.Namespace(
        cuda=use_cuda, seed=options.seed, batch_size=16, lr=5e-5,
        warmup_steps=2000, max_grad_norm=1.0,
        no_sequence_shuffle=False, no_synchronous_learning=False, no_repeated_sequence=False,
        max_turn=20, min_probability=0.012, end_probability=0.9,
        model_config=str(UPSTREAM / "config/diaformer_config.json"),
        pretrained_model=None, model_output_path=None, result_output_path=None,
    )
    module.tokenizer = module.diaTokenizer(str(UPSTREAM / "data/dxy_dataset/vocab.txt"))
    tokenizer = module.tokenizer
    # The pinned upstream loss accepts class_weight but does not use it.
    tokenizer.class_weight = torch.ones(len(tokenizer.vocab))
    train_tokens = tokenize(training, tokenizer)
    model, _ = module.create_model(module.args, tokenizer)
    model.to(device)
    train_loader = DataLoader(
        module.diaDataset(train_tokens), batch_size=16, shuffle=True,
        num_workers=0, collate_fn=module.collate_fn_train, drop_last=True,
    )
    optimizer = module.AdamW(model.parameters(), lr=5e-5, correct_bias=True)
    total_steps = int(len(train_tokens) * epochs / 16)
    scheduler = module.WarmupLinearSchedule(optimizer, warmup_steps=2000, t_total=total_steps)
    upstream_commit = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True,
    ).strip()
    config = {
        "mode": "smoke_validation_only" if options.smoke else "baseline",
        "seed": options.seed, "epochs": epochs, "eval_every": options.eval_every,
        "training_cases": len(train_tokens), "training_split_cases": len(training),
        "empty_training_cases_skipped": len(training) - len(train_tokens),
        "original_training_cases": len(data["train"]), "validation_cases": len(validation),
        "original_test_cases": len(data["test"]), "upstream_commit": upstream_commit,
        "python": platform.python_version(), "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(0) if use_cuda else "cpu",
        "model_config": model.config.to_dict(),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "batch_size": 16, "learning_rate": 5e-5, "warmup_steps": 2000,
        "max_turn": 20, "min_probability": 0.012, "end_probability": 0.9,
        "validation_fraction": 0.2, "precision": "float32",
        "selection": "maximum validation 0.8*diagnosis_accuracy + 0.2*symptom_f1",
    }
    (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (output / "split_indices.json").write_text(json.dumps({
        "train": training_indices, "validation": validation_indices,
    }), encoding="utf-8")
    print(json.dumps({"event": "start", **config}), flush=True)
    started = time.perf_counter()
    best_score, best_epoch, best_validation = -1.0, None, None
    checkpoint = output / "best_model.pt"
    with (output / "history.jsonl").open("w", encoding="utf-8") as history:
        for epoch in range(1, epochs + 1):
            model.train()
            loss_sum = 0.0
            batches = 0
            for batch in train_loader:
                batch = [tensor.to(device) for tensor in batch]
                (input_ids, labels, diseases, attention, encoder_labels, encoder_pos,
                 decoder_pos, decoder_weights, symptom_mask, symptom_types, answer_types) = batch
                optimizer.zero_grad(set_to_none=True)
                outputs = model(
                    input_ids=input_ids, issym=False, isdis=True, attention_mask=attention,
                    encoderpos=encoder_pos, sym_type_ids=symptom_types, ans_type_ids=answer_types,
                )
                symptom_loss, _ = module.lm_loss_func(
                    outputs[0][..., :len(tokenizer.vocab)], labels, decoder_pos,
                    decoder_weights, symptom_mask, class_weight=tokenizer.class_weight.to(device),
                )
                disease_loss, _ = module.mc_loss_func(outputs[2], mc_labels=diseases)
                loss = symptom_loss + disease_loss
                if not torch.isfinite(loss):
                    raise RuntimeError("Non-finite training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                loss_sum += float(loss.detach())
                batches += 1
                if options.smoke and batches == 2:
                    break
            entry = {"epoch": epoch, "training_loss": loss_sum / batches, "batches": batches}
            if epoch % options.eval_every == 0 or epoch == epochs:
                metrics = evaluate(
                    module, model, device, validation, output / f"validation-{epoch:03d}.json",
                )
                entry["validation"] = metrics
                if metrics["selection_score"] > best_score:
                    best_score, best_epoch, best_validation = metrics["selection_score"], epoch, metrics
                    torch.save(model.state_dict(), checkpoint)
            entry["elapsed_seconds"] = time.perf_counter() - started
            history.write(json.dumps(entry) + "\n")
            history.flush()
            print(json.dumps(entry), flush=True)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    test = None if options.smoke else evaluate(
        module, model, device, data["test"], output / "test-predictions.json",
    )
    summary = {
        "config": config, "best_epoch": best_epoch, "validation": best_validation,
        "test": test, "elapsed_seconds": time.perf_counter() - started,
        "peak_cuda_memory_mib": torch.cuda.max_memory_allocated() / 2**20 if use_cuda else None,
        "checkpoint": "best_model.pt", "status": "complete",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"event": "complete", **summary}), flush=True)
