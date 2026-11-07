# 数据与代码准备状态

核查日期：2026-11-07。此处记录当前实际文件与检查结果，任务及后续结果由三位负责人更新各自 TASKS.md。

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

Synthetic：BIBM 表 I 报告 444 种症状，当前文件实际出现 266 种，现有词表也对应 266 种症状。是否属于版本或统计口径差异需老师确认，不静默视为同一版本。

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

已检查字段、非空及患者范围一致性。CSV 列名为小写，上游旧程序可能使用大写，适配时处理。后续就诊关联、时间排序、编码映射和筛选尚未实现。

Demo 支持数据流程开发，不足以复现论文指标。完整 MIMIC-III 权限和数据尚未确认取得；MIMIC-IV 放在后续扩展。

复查命令：python scripts/fetch_public_demo.py --check-only。

## 已取得的代码

| 代码 | 位置与版本 | 当前能确认什么 |
|---|---|---|
| SSPNet | third_party/SSPNet；4a2695ec67e0dc30cd3fa8e67a4f1536f0bfc90d | main.py、模型、训练与评价代码存在；尚未运行模型 |
| Diaformer | third_party/Diaformer；45491f33145003290278d0eacdc87a1d1d786b2d | 问诊代码、三个数据目录、词表和预处理代码存在；尚未运行模型 |
| BIBM 完整实现 | 尚未取得 | 不能将 Diaformer 记作整篇 BIBM 的实现 |

原始来源：[SSPNet](https://github.com/ResearchGroupHdZhang/SSPNet)、[Diaformer](https://github.com/jymChen/Diaformer)。
BIBM DOI：10.1109/BIBM58861.2023.10385557；SSPNet [正式论文](https://www.ijcai.org/proceedings/2025/1052.pdf)。

## 目前阻塞

### SSPNet

当前入口读取下面五个文件，均尚未在该代码的 data/MIMIC_3 目录中准备：

- records_final.pkl：病例序列。
- voc_final.pkl：诊断、操作和药物词表。
- ehr_adj_final.pkl：药物共现图。
- ddi_A_final.pkl：与词表对齐的药物相互作用图。
- ddi_mask_H.pkl：当前入口还会读取的辅助文件，需核对实际用途。

缺失配套预处理与映射材料：作者使用的 processing.py、药物编码映射、DDI 原始来源和生成设置。不要从不同仓库拼接不匹配的同名文件。

作者正文引用的附录尚未取得；正文学习率 1e-4 与当前入口默认 5e-4 不一致，需记录采用设置。B 负责向老师集中核对。

### BIBM

缺完整知识提取、规则迭代、MLN 学习与推理代码，提示词、规则文件和相关设置。C 向老师取得；原诊断任务与用药核查扩展分开实施。

### 环境与资源

本次检查使用的 Python 3.14 解释器有 numpy，但未安装 torch、dill；未安装完整复现环境。不能据此判断所有机器环境。

Diaformer 作者报告 Python 3.8 / PyTorch 1.8.0，SSPNet 报告 Python 3.8.16 / PyTorch 1.9.0。B/C 分别建立隔离环境并核实兼容性，不直接在最新 Python 上堆装旧依赖。

可用 GPU、完整 MIMIC 审批和大模型调用资源仍未确认。本轮没有训练、付费调用或新增实验指标。

## 现在可以推进什么

- A：利用 Demo 编写就诊关联和按时间组织历史的最小数据流程，同时办理完整数据权限与资源。
- B：拿到配套材料后准备模型输入，先跑通入口，再开展正式训练与关键对照。
- C：诊断数据已经可读取，先搭 DXY / Diaformer 的问诊基线环境；取得 BIBM 代码后接上知识与 MLN。

当前优先级：可复查数据流程与基线入口 → 两篇分别复现 → 推荐与知识核查结合 → agent 展示。

