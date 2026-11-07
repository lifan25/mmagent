"""Export readable local examples from the bundled and downloaded case files."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from check_diagnosis_data import DataOnlyUnpickler


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/data-preview"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def select_visits(base, synthetic=False):
    if synthetic:
        names = ("encounters", "conditions", "procedures", "medications")
        patient_key, visit_key, start_key, link_key = "PATIENT", "Id", "START", "ENCOUNTER"
    else:
        names = ("ADMISSIONS", "DIAGNOSES_ICD", "PROCEDURES_ICD", "PRESCRIPTIONS")
        patient_key, visit_key, start_key, link_key = "subject_id", "hadm_id", "admittime", "hadm_id"
    admissions = read_csv(base / f"{names[0]}.csv")
    indices = []
    for name in names[1:]:
        index = defaultdict(list)
        for row in read_csv(base / f"{name}.csv"):
            index[row[link_key]].append(row)
        indices.append(index)
    eligible = [a for a in admissions if all(index.get(a[visit_key]) for index in indices)]
    counts = Counter(a[patient_key] for a in eligible)
    patient = next(a[patient_key] for a in eligible if counts[a[patient_key]] >= 2)
    selected = sorted((a for a in eligible if a[patient_key] == patient), key=lambda a: a[start_key])[:3]
    visits = []
    for admission in selected:
        visit = {"admission": admission}
        for field, index in zip(("diagnoses", "procedures", "medications"), indices):
            rows = index[admission[visit_key]]
            if any(row[patient_key] != patient for row in rows):
                raise ValueError("Encounter join crossed patient boundaries")
            visit[field] = rows
        visits.append(visit)
    return {"source": str(base), "patient_id": patient, "synthetic": synthetic,
            "selection": "Up to three chronological encounters with recorded diagnosis, procedure and medication; not the full history or a training split.",
            "visits": visits}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dxy_path = ROOT / "third_party/Diaformer/data/dxy_dataset/goal_set.p"
    with dxy_path.open("rb") as source:
        dxy = DataOnlyUnpickler(source).load()["train"][:10]
    examples = {"dxy.train.first10.json": dxy}
    sections = [
        "# 病例文件预览\n",
        "这些内容由实际数据文件导出，保存在本地 outputs，不提交病例级内容。\n",
        "## DXY：中文问诊\n",
        f"原始文件：`{dxy_path}`。前十条完整记录见 `dxy.train.first10.json`。\n",
        "self_repo 是主诉；explicit_inform_slots 是主动告知的症状；implicit_inform_slots 是问诊模拟中询问后才能获得的答案。true/false 是有/无，未列出的症状不等于不存在。disease_tag 是标准答案，dialog 可能包含诊断结论，不能整体作为诊断输入。\n",
        "第一条记录原样导出：\n\n```json\n" + json_text(dxy[0]) + "```\n",
    ]
    datasets = [("MIMIC Demo：真实去标识化住院记录", ROOT / "data/public/mimiciii-demo-1.4", False, "mimic_demo.one_patient.json"),
                ("Synthea：合成患者的多次就诊", ROOT / "data/local/synthea-apr2020", True, "synthea.one_patient.json")]
    for title, base, synthetic, filename in datasets:
        if not base.exists():
            continue
        case = select_visits(base, synthetic)
        examples[filename] = case
        sections.extend([f"## {title}\n", f"原始目录：`{base}`。所选就诊的完整原始行见 `{filename}`。\n",
                         f"患者编号：`{case['patient_id']}`。仅展示同一患者至多三次同时记录诊断、操作、用药的就诊，不代表完整病史。\n"])
        for i, visit in enumerate(case["visits"], 1):
            admission = visit["admission"]
            date = admission["START" if synthetic else "admittime"]
            sections.append(f"### 就诊 {i}：{date}\n")
            for field, label in (("diagnoses", "诊断"), ("procedures", "操作")):
                values = [f"{r['CODE']}：{r['DESCRIPTION']}" if synthetic else r["icd9_code"] for r in visit[field]]
                sections.append(f"{label}（共 {len(values)} 条，最多列六条）：" + "；".join(values[:6]) + "。\n")
            drugs = visit["medications"]
            sections.append(f"记录中的用药（共 {len(drugs)} 行，最多列六行）：\n")
            for row in drugs[:6]:
                value = f"{row['CODE']}：{row['DESCRIPTION']}" if synthetic else f"{row['drug']}；NDC={row['ndc']}；剂量={row['dose_val_rx']} {row['dose_unit_rx']}；途径={row['route']}"
                sections.append(f"- {value}\n")
        sections.append("\n这里的用药是数据中记录的处方，不是模型推荐结果。预测当前就诊时，当前药物应留作答案；历史药物仅来自此前就诊。\n")
    sections.extend(["## 数据的区别\n",
                     "DXY 的中文症状问诊与住院病历没有患者对应关系，不能直接拼接成一条真实病例。MIMIC 使用 ICD/NDC 等编码；本次 Synthea 使用 SNOMED CT 诊断/操作及 RxNorm 药物编码，需要分别组织词表并核对药物映射。\n",
                     "Synthea 是模拟病历，可用于开发和模拟实验，其结果不能直接代表真实临床表现。CSV 中的空字段保留为空，不擅自补全。\n"])
    for name, example in examples.items():
        (OUT / name).write_text(json_text(example), encoding="utf-8")
    preview = OUT / "病例预览.md"
    preview.write_text("\n".join(sections), encoding="utf-8")
    print(preview)
    print(json.dumps({name: len(value) if isinstance(value, list) else len(value["visits"]) for name, value in examples.items()}))


if __name__ == "__main__":
    main()
