"""Run frozen, label-free pilot inputs against a local-only inference server."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MODEL = "qwen3-4b-instruct-2507-q4km"
PROMPTS = {"lists": "ddi-list-local-v1.txt", "corpus": "ddicorpus-local-v1.txt"}


def model_input(row, task):
    if task == "lists":
        return {k: row[k] for k in [*(f"drug{i}" for i in range(1, 7)), "doses"]}
    value = row["input"]
    return {"sentence": value["sentence"],
            **{name: {key: value[name][key] for key in ("text", "charOffset")} for name in ("entity1", "entity2")}}


def run(inputs, task, output, runtime, port):
    if output.exists():
        raise ValueError("Run directory exists; preserve the first attempt and use a new version")
    rows = [json.loads(line) for line in inputs.read_text(encoding="utf-8").splitlines()]
    assert len({r["case_id"] for r in rows}) == len(rows), "Duplicate input cases"
    payloads = [model_input(row, task) for row in rows]
    prompt_path = ROOT / "src/knowledge/prompts" / PROMPTS[task]
    prompt = prompt_path.read_text(encoding="utf-8")
    output.mkdir(parents=True)
    settings = {"model": MODEL, "temperature": 0, "top_p": 1, "seed": 20261114,
                "max_tokens": 128, "stream": False, "response_format": {"type": "json_object"}}
    info = {"started_utc": datetime.now(timezone.utc).isoformat(), "task": task,
            "repository_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "input_file": inputs.resolve().relative_to(ROOT).as_posix(), "samples": len(rows),
            "input_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
            "prompt_file": prompt_path.relative_to(ROOT).as_posix(), "prompt": prompt,
            "request_settings": settings, "runtime": json.loads(runtime.read_text(encoding="utf-8")),
            "endpoint": f"http://127.0.0.1:{port}/v1/chat/completions", "status": "running"}
    (output / "run-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    start = time.perf_counter()
    tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    latencies = []
    with (output / "responses.jsonl").open("x", encoding="utf-8") as f:
        for index, (row, data) in enumerate(zip(rows, payloads), 1):
            payload = {**settings, "messages": [{"role": "system", "content": prompt},
                                              {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}
            request = Request(info["endpoint"], data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"})
            begin = time.perf_counter()
            with urlopen(request, timeout=180) as response:
                result = json.load(response)
            latency = time.perf_counter()-begin
            choice = result["choices"][0]
            usage = result.get("usage", {})
            record = {"case_id": row["case_id"], "response": choice["message"]["content"],
                      "finish_reason": choice.get("finish_reason"), "usage": usage, "seconds": latency}
            f.write(json.dumps(record, ensure_ascii=False)+"\n")
            f.flush()
            latencies.append(latency)
            for key in tokens:
                tokens[key] += usage.get(key, 0)
            if index % 5 == 0 or index == len(rows):
                print(json.dumps({"task": task, "completed": index, "total": len(rows),
                                  "elapsed_seconds": round(time.perf_counter()-start, 2)}), flush=True)
    info.update(status="completed", seconds=time.perf_counter()-start, token_usage=tokens,
                mean_request_seconds=sum(latencies)/len(latencies), max_request_seconds=max(latencies))
    (output / "run-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--task", choices=PROMPTS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    run(args.inputs, args.task, args.output, args.runtime, args.port)
