# 数据与代码准备状态

核查日期：2026-11-07。此处记录当前实际文件与检查结果，任务及后续结果由三位负责人更新各自 TASKS.md。

准备结论：开发用的原始数据、参考预处理、药物映射和 DDI 已找到并在本机保存。A1 已生成两套数据的审计、筛选病例和患者划分，见 [A1 报告](../src/data_evaluation/reports/data-summary.md)；SSPNet 整数词表/模型文件/最终映射图尚未生成，真实大规模验证队列尚未取得。文件已在本机，不代表其他成员克隆仓库后自动取得所有本地大文件。分工和 PR 修改范围见 [协作规则](../CONTRIBUTING.md)。

新成员按 [三人开工步骤](onboarding.md) 取得材料并做本机检查；不要把资源清单中组长电脑的已完成结果当作自己的验证记录。

当前路线：用户已同意采用相关公开数据和上游材料，不再等待作者提供完全相同的实验产物。保留 DXY 基线；推荐流程先用 MIMIC Demo 和 Synthea 合成病历开发，正式真实病例实验仍需足够规模的真实数据。更换数据属于适配实验，不能直接沿用原论文指标，也不单独构成研究贡献。

## 已取得并检查的数据

### 诊断数据

来源：[Diaformer 作者仓库](https://github.com/jymChen/Diaformer)，固定提交 45491f33145003290278d0eacdc87a1d1d786b2d。
文件：third_party/Diaformer/data/<数据集>_dataset/goal_set.p。

| 数据集 | 训练病例 | 测试病例 | 非空验证集 | 疾病数 | 文件中实际出现的症状数 |
|---|---:|---:|---|---:|---:|
| DXY | 423 | 104 | 无 | 5 | 41 |
| Muzhi | 568 | 142 | 无 | 4 | 66 |
| Synthetic | 24000 | 6000 | 无 | 90 | 266 |

已检查：文件可读取；train/test 非空；病例具有疾病标签和显式/隐含症状字典；当前症状值为布尔值；没有覆盖或重新划分原数据。

DXY、Muzhi 上述数量与 BIBM 表 I 一致，可以作为首轮目标；这不代表预处理、环境和模型训练已完成。先用 DXY 开始。

Synthetic：BIBM 表 I 报告 444 种症状，当前文件实际出现 266 种，现有词表也对应 266 种症状。采用手头版本时记录差异，不作为等待老师回复的前置条件。此诊断数据集与下文 Synthea 合成病历是两种不同的数据。

现有数据没有非空验证集。C 应核对作者的模型选择方法；需要增加验证集时从训练部分划分并记录偏差，不能以测试集反复选参。

复查命令：python scripts/check_diagnosis_data.py。

### MIMIC-III 公开 Demo

来源：[官方 Demo v1.4](https://physionet.org/content/mimiciii-demo/1.4/)。
位置：data/public/mimiciii-demo-1.4/。五张原始表、原许可证和来源说明已加入仓库。

| 表 | 数据行数 | 涉及患者数 |
|---|---:|---:|
| PATIENTS | 100 | 100 |
| ADMISSIONS | 129 | 100 |
| DIAGNOSES_ICD | 1761 | 100 |
| PROCEDURES_ICD | 506 | 88 |
| PRESCRIPTIONS | 10398 | 94 |

已检查字段、非空及患者范围一致性。CSV 列名为小写，上游旧程序可能使用大写。A1 已完成就诊关联、时间排序和候选筛选；药物分类映射仍由 B 实施。

Demo 支持数据流程开发，不足以复现论文指标。完整 MIMIC-III 权限和数据尚未确认取得；MIMIC-IV 放在后续扩展。

复查命令：python scripts/fetch_public_demo.py --check-only。

### Synthea 合成病历：推荐流程的替代开发数据

来源：[官方公开下载页](https://synthetichealth.github.io/downloads.html) 的历史 1K CSV 样本，[2020 年 4 月固定文件](https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_csv_apr2020.zip)。官方说明数据可用于研究等用途、不受真实患者隐私限制。原始压缩包缓存于 .cache；抽取的六张 CSV 在 data/local/synthea-apr2020/，保持本地，不自动提交病例。

实际检查：患者 1,171 人，就诊 53,346 行，诊断 8,376 行，操作 34,981 行，用药 42,989 行，过敏 597 行。下载页的“1K”是样本名称，不是精确统计。

- 1,257 次就诊同时记有诊断、操作、药物；其中有至少两次此类就诊的患者 335 人，至少三次的 117 人。这是原始记录交集检查，尚未做最终筛选或训练划分。
- 本样本使用 SNOMED CT 诊断/操作及 RxNorm 药品编码；不能直接套用 MIMIC 的 ICD/NDC 处理。需按数据集单独建词表，并将药物映射到 DDI 支持的编号。
- 对 MoleRec 现有映射做 RXCUI 精确匹配：131 种原始 RxNorm 编码中 101 种有匹配，对应用药行 32,062/42,989。这个 131 是本样本的原始药品编码数，不等同于 SSPNet 论文的 131 种药物。尚未做成分归一化；未映射药物不能当作没有相互作用。
- 合成病历支持开发、接口验证和模拟实验，不能将其得分当作真实临床效果。慢性病的跨就诊延续等处理需单独定义，不默认补全。

下载/检查：python scripts/fetch_synthea_sample.py；只检查：python scripts/fetch_synthea_sample.py --check-only。

### 直接查看病例

运行 python scripts/preview_cases.py，生成本地 outputs/data-preview/病例预览.md，以及 dxy.train.first10.json、mimic_demo.one_patient.json、synthea.one_patient.json。预览保持原字段，展示病例标签和已有处方，不是模型预测，也不是训练输入文件。全部忽略提交。

DXY 包含中文主诉、问诊及症状；MIMIC/Synthea 按多张 CSV 存储就诊、诊断、操作、药物。它们没有共同患者，不能拼接成一条真实病例。

## 已取得的代码

| 代码 | 位置与版本 | 当前能确认什么 |
|---|---|---|
| SSPNet | third_party/SSPNet；4a2695ec67e0dc30cd3fa8e67a4f1536f0bfc90d | main.py、模型、训练与评价代码存在；尚未运行模型 |
| Diaformer | third_party/Diaformer；45491f33145003290278d0eacdc87a1d1d786b2d | DXY 150 轮训练、验证选模、权重保存与重载、最终测试已完成：79/104，75.96%；见运行说明 |
| BIBM 完整实现 | 尚未取得 | 不能将 Diaformer 记作整篇 BIBM 的实现 |
| MoleRec 参考材料 | data/reference/MoleRec/（本地）；dd5afaf0a503fd3de3229f86ec7f26b345d10e3a | 已复制原预处理脚本、映射、分子辅助材料及原 README/LICENSE；不是 SSPNet 作者配套数据 |

原始来源：[SSPNet](https://github.com/ResearchGroupHdZhang/SSPNet)、[Diaformer](https://github.com/jymChen/Diaformer)。
BIBM DOI：10.1109/BIBM58861.2023.10385557，[作者主页提供的论文 PDF](https://hdzhangust.github.io/static/files/papers/2023%20BIBM%20Integrating%20Automated%20Knowledge%20Extraction.pdf)；SSPNet [正式论文](https://www.ijcai.org/proceedings/2025/1052.pdf)。

## 已找到的参考材料与剩余工作

### SSPNet

当前入口读取下面五个文件，均尚未在该代码的 data/MIMIC_3 目录中准备：

- records_final.pkl：病例序列。
- voc_final.pkl：诊断、操作和药物词表。
- ehr_adj_final.pkl：药物共现图。
- ddi_A_final.pkl：与词表对齐的药物相互作用图。
- ddi_mask_H.pkl：当前入口还会读取的辅助文件，需核对实际用途。

公开参考材料已经找到并保存到本地 data/reference/MoleRec/：processing.py、ndc2rxnorm_mapping.txt、ndc2atc_level4.csv、drug-atc.csv、atc2rxnorm.pkl、idx2SMILES.pkl、ddi_mask_H.py、ddi_mask_H.pkl、substructure_smiles.pkl。保留原 README、MIT LICENSE 与 source.json；来源是 [MoleRec](https://github.com/yangnianzu0515/MoleRec)，SSPNet README 也致谢该项目和 [SafeDrug](https://github.com/ycq091044/SafeDrug)。使用这些上游材料适配，不再等待相同文件由老师重发。

DDI 原始文件已从 SSPNet/MoleRec 提供的 [公开下载入口](https://drive.google.com/file/d/1s3sHmz9ueVA8YAGTARY8jwrhRdRvVaXs/view) 下载到上述目录 drug-DDI.csv：232,835,373 字节，4,649,441 条数据行，含 STITCH 1、STITCH 2、Polypharmacy Side Effect、Side Effect Name 字段。原始来源为 [TwoSIDES](https://tatonettilab.org/resources/tatonetti-stm.html)。这是药物对与不良事件记录，尚未筛选为模型的 ddi_A_final.pkl，也不等同于这么多独立药物对。

下一步对 Demo/Synthea 分别建立病例、词表与图，固定映射及筛选方式。上游预生成的分子矩阵不能与新的药物词表混用。公开 SSPNet 的 training.py 传三个参数、模型 forward 要求四个，需在本项目适配入口修正并实际检查；ddi_mask_H 在该实现的用途仍需梳理。

作者正文引用的附录尚未取得；正文学习率 1e-4 与当前入口默认 5e-4 不一致，采用设置必须记录。附录与作者精确配置作为可选补充，不阻塞公开材料上的适配开发。

### BIBM

尚未找到完整知识提取、规则迭代、MLN 学习与推理的公开整套实现和作者生成产物。论文已给出部分提示词模板与设置，不能称提示词全部缺失。[Alchemy](https://alchemy.cs.washington.edu/) 本体公开可得。C 可据原文自行实现最小流程并记录差异，不必先等作者完整代码；作者规则和缓存可后补对照。原诊断任务与用药核查扩展分开实施。

### 环境与资源

项目 .venv 已配置 Python 3.10.22、PyTorch 2.7.1+cu128 和锁定依赖。RTX 5060 Laptop GPU 约 8GB 显存，已通过实际矩阵计算与 DXY 冒烟训练；运行说明见 [DXY 基线](dxy-diaformer.md)。

Diaformer 作者报告 Python 3.8 / PyTorch 1.8.0；本次为适配现有显卡使用现代环境并记录运行差异。SSPNet 原环境与配套依赖仍需单独核对，不能因为 DXY 已运行就视为它也就绪。

完整 MIMIC 审批和大模型调用资源仍未确认。DXY 本轮没有付费调用，已使用本机 GPU 完成；这不表示 BIBM 整体或 SSPNet 已具备全部复现条件。

## 现在可以推进什么

- A：使用现有 Demo/Synthea 编写就诊关联、时间组织和数据集独立划分，统计筛选后的有效患者；完整 MIMIC 申请可并行进行。
- B：基于已找到的 MoleRec 映射和 DDI，与 A 对齐词表，修正运行接口并生成一致的模型输入，先实际跑通入口。
- C：复用 DXY 基线，按论文已有模板实现最小规则与 MLN 流程；缺付费模型调用条件时先用明确标记的规则样例联调，不能冒充自动知识提取实验。

当前优先级：公开材料上的数据流程与模型入口 → 两篇核心机制的适配验证 → 推荐与知识核查结合 → agent 展示。真实数据研究与原文严格复现的条件另行记录。

