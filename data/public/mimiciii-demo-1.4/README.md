# MIMIC-III Clinical Database Demo v1.4

本目录收录官方公开 Demo 的五张原始 CSV 表及原始许可证，文件未修改。它们与需要身份审核的完整 MIMIC-III 数据不同，无需申请即可按原许可访问。

- 发布者：Alistair Johnson、Tom Pollard、Roger Mark，PhysioNet。
- 数据页：https://physionet.org/content/mimiciii-demo/1.4/
- 原始文件：https://physionet.org/files/mimiciii-demo/1.4/
- 引用：Johnson, A., Pollard, T., & Mark, R. (2019). MIMIC-III Clinical Database Demo (version 1.4). PhysioNet. https://doi.org/10.13026/C2HM2Q
- 许可证：Open Data Commons Open Database License v1.0；见本目录 LICENSE.txt。
- 核查日期：2026-11-07。

Contains information from MIMIC-III Clinical Database Demo v1.4, made available by PhysioNet under the Open Database License (ODbL). Original license and attribution remain applicable to these tables.

## 文件和用途

| 文件 | 用途 |
|---|---|
| PATIENTS.csv | 确认 Demo 的患者范围 |
| ADMISSIONS.csv | 就诊关联和实际时间顺序 |
| DIAGNOSES_ICD.csv | 诊断编码 |
| PROCEDURES_ICD.csv | 操作编码 |
| PRESCRIPTIONS.csv | 用药记录 |

该 Demo 包含 100 名患者，不含临床自由文本记录。其患者选自完整库中最终死亡的患者，并非代表完整训练分布的随机临床队列。

本次官方 CSV 的列名为小写（如 subject_id）；部分上游旧预处理程序使用大写（如 SUBJECT_ID）。原文件保持不变，B 在数据适配中显式处理列名差异，不能直接假定 Demo 可原样运行旧脚本。

可用于字段检查、数据读取与小规模流程开发；不能作为 SSPNet 原论文的完整数据复现或泛化证据。获得完整库后应另设目录，不能覆盖这里的 Demo。

## 下载和检查

在项目根目录执行：

```powershell
python scripts/fetch_public_demo.py
python scripts/fetch_public_demo.py --check-only
```

脚本只检查字段、非空、100 名患者以及各表患者归属，输出汇总数量。它不执行模型、不处理药物映射、不计算论文指标。

2026-11-07 实际检查结果：

| 表 | 数据行数 | 涉及患者数 |
|---|---:|---:|
| PATIENTS | 100 | 100 |
| ADMISSIONS | 129 | 100 |
| DIAGNOSES_ICD | 1761 | 100 |
| PROCEDURES_ICD | 506 | 88 |
| PRESCRIPTIONS | 10398 | 94 |

各表患者范围不同，不能假设所有 100 人都满足药物推荐预处理的条件；后续筛选可能进一步缩小样本。
