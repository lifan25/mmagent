# 三人开工步骤

这份说明用于第一次拉取仓库和开始第一批工作。具体任务与状态只维护在各模块 TASKS.md；共享字段以 [protocol.md](protocol.md) 为准。

## 1. 拉取最新框架

首次下载：

```powershell
git clone --recurse-submodules https://github.com/lifan25/mmagent.git
Set-Location mmagent
```

已经有本地仓库：先保存自己的未提交修改，再执行：

```powershell
git switch main
git pull --ff-only
git submodule update --init --recursive
```

A1 已提供可运行的 Demo/Synthea 病例准备、患者划分与测试，命令见 A 模块 README；B/C 以及 A2/A3 尚待实现。三位成员在各自目录继续开发，现有基线脚本保持原样。

## 2. 按角色阅读，不需要先看完整个仓库

| 角色 | 阅读顺序 | 第一批任务 | 不依赖其他成员也能先做什么 |
|---|---|---|---|
| A：@lifan25 | [模块 README](../src/data_evaluation/README.md) → [TASKS](../src/data_evaluation/TASKS.md) → [协议](protocol.md) | A1：病例组织与患者划分 | 查看源表、关联字段、定义筛选、建立划分 |
| 成员 B | [模块 README](../src/recommendation/README.md) → [TASKS](../src/recommendation/TASKS.md) → SSPNet/MoleRec 来源 | B1：药物映射 | 读取原始药物列、统计精确映射与未匹配情况 |
| 成员 C | [模块 README](../src/knowledge/README.md) → [TASKS](../src/knowledge/TASKS.md) → BIBM 原文与 [DXY 基线](dxy-diaformer.md) | C1：规则流程与来源 | 梳理提示词/谓词、明确规则字段、检查 MLN 后端环境 |

三人都阅读 [CONTRIBUTING.md](../CONTRIBUTING.md) 中的目录范围和 PR 操作。B/C 暂用角色名，账号由 A 确定后填写；不自行认领别人的目录。

## 3. 在自己的电脑确认数据

“组长电脑已经下载”不代表所有文件随 git pull 到了每个人电脑。来源、版本和数量以 [资源清单](resources.md) 为准。

| 材料 | 克隆后是否自带 | 取得方式和用途 |
|---|---|---|
| DXY/Muzhi/Synthetic 诊断集 | 子模块初始化后自带 | third_party/Diaformer/data/；主要给 C 的诊断分支 |
| MIMIC-III Demo 五张表 | 自带 | data/public/mimiciii-demo-1.4/；核对关联与 MIMIC 字段 |
| Synthea 2020-04 合成 CSV | 不自带 | 现有 scripts/fetch_synthea_sample.py 下载；首轮推荐模拟开发数据 |
| MoleRec 参考预处理与映射 | 不自带 | 下载下面的固定提交，取所需 data/ 材料并保留根 README/LICENSE |
| drug-DDI.csv | 不自带 | 从资源清单的原作者 Drive 入口下载，本地保存为 CSV |

[MoleRec 固定提交](https://github.com/yangnianzu0515/MoleRec/tree/dd5afaf0a503fd3de3229f86ec7f26b345d10e3a)；[该提交 ZIP](https://github.com/yangnianzu0515/MoleRec/archive/dd5afaf0a503fd3de3229f86ec7f26b345d10e3a.zip)。B 将所需映射/预处理原始文件放 data/reference/MoleRec/，另保留原项目 README 和 LICENSE；文件清单见资源清单。不要把原项目的现成权重和不同词表产物当作本项目模型输入。

现有数据检查和下载命令（使用自己已安装的 Python；这些数据脚本无需 PyTorch）：

```powershell
python scripts/check_diagnosis_data.py
python scripts/fetch_public_demo.py --check-only
python scripts/fetch_synthea_sample.py
python scripts/fetch_synthea_sample.py --check-only
python scripts/preview_cases.py
```

预览在 outputs/data-preview/病例预览.md。DDI 应是含 STITCH 1、STITCH 2、Polypharmacy Side Effect、Side Effect Name 字段的 CSV，而不是下载页面的 HTML。首次下载失败时记录报错和实际文件类型，不将错误页面当数据继续处理。

每个人在自己的 TASKS.md 中填写“本机准备情况”：Python、设备、取得哪些文件、来源版本、聚合检查结果。只填自己核验过的内容；不复制组长机器上的 .venv、绝对路径或“已运行”结论。

## 4. 目录怎么用

每个模块已有 README.md、TASKS.md、AGENTS.md，以及 configs/、tests/、reports/；C 另外有 prompts/、rules/。空目录用 .gitkeep 保留，成员添加真实文件后可删除占位。

- README.md：模块结构、实际安装/运行命令及产物位置。
- TASKS.md：待办、进度、阻塞、验收证据和交接，不再建另一套进度文档。
- configs/：该模块可复查的设置；不放密钥和他人电脑的绝对路径。
- tests/：少量有意义的手算/边界/集成检查；由成员随实现补充。
- reports/：可提交的聚合统计和实验报告，使用现有模板；不放病例与权重。
- prompts/、rules/：由 C 填写带来源和版本的模板/规则；候选审核前保持 draft。

大文件仍写到各自被 Git 忽略的 data/processed/<模块>/、outputs/<模块>/、models/<模块>/，不是放进 reports/。

## 5. 第一批 PR 怎么拆

| PR | 只交付这一项 | 审核时看什么 |
|---|---|---|
| a/cases-and-split | A1 病例组织、患者划分、汇总与运行说明 | 数据来源、筛选人数、患者不交叉、时间与标签边界 |
| b/drug-mapping | B1 映射和覆盖统计、小样例检查、编码建议 | 药物层级、一对多、未匹配处理，以及统计口径 |
| c/rule-pipeline | C1 阶段流程、模板/规则字段与来源、后端环境检查记录 | 原文和自实现分开，来源可定位，环境结论有证据 |

这三个 PR 可同时推进。A1 交付后 B 做 B2；A2 的手算指标检查可独立进行；C2 诊断和 C3 核查可并行；B3/C3 接口通过后 A 做 A3。首批 PR 不要求完整训练或网页展示。

成员从最新 main 建立自己的 a/、b/、c/ 分支，完成后推送分支并向 main 提 PR。git pull 是取得别人已合并的工作，PR 是提交自己的工作请组长审核，两者不是一件事。

## 6. 开工时先确认的少数问题

1. A 记录筛选和患者划分；B 记录输出药物编号究竟代表成分还是分类。正式集成前由 A 汇总到共享协议。
2. 先用一个数据集跑通推荐，建议 Synthea；Demo 检查字段，真实大规模数据另行准备。不要一开始同时适配所有数据、重跑全部论文表格。
3. B/C 用共享虚构样例独立检查字段，等待真实产物时也能继续工作；实际评价只使用相应真实/合成数据的结果。
4. 卡住时在 TASKS.md 写“输入版本、执行步骤、实际错误、已尝试什么、需要谁提供什么”，由 A 决定下一步。保留已能独立验收的部分。
