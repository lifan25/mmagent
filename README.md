# 有医学知识依据的个性化用药推荐 agent

目标：SSPNet 产生个性化候选药物，借鉴 BIBM 的知识提取与规则化方法核查结果，由 agent 组织输入检查、工具调用和展示。

当前优先级：补齐BIBM知识模块与SSPNet共享接口，完成上述agent调用链，再做模块消融；零样本和DialMed只作补充。Qwen及额外CUDA运行库均非项目必需项，已有环境足够继续主线实现。

第一版使用已有诊断与结构化病历。DXY/Diaformer已完成150轮运行，原104条测试正确79条（75.96%）。SSPNet当前38类已完成20轮适配训练和重载，Jaccard74.65%、F1 80.91%，见[运行报告](src/recommendation/reports/sspnet-synthea-product-v4.md)。2026-11-14完成[DDI溯源、损失探针与简单基线](src/recommendation/reports/ddi-audit-20261114.md)；当前DDI率不能直接解释为临床风险。BIBM整体、严格复现和agent集成仍未完成。

研究阶段先看[当前研究设计（含零样本对照）](docs/research-design.md)和[MIMIC-IV本人申请步骤](docs/mimic-access.md)。现有Synthea测试已用于错误分析，作为探索性结果；正式确认需未参与开发的真实数据。

最新推进暂不依赖申请中数据：已取得DDICorpus-2013、DDInter七分类和DialMed的dev/test，实际完成文本抽取轻量训练、清单位置基线与独立知识库检索实验，见[新数据与实验报告](src/knowledge/reports/open-data-pilot-20261114.md)。发现原清单位置泄露参考后已固定置换；大模型下载尚未完成，零样本推理没有结果。

**刚拉取仓库：先看 [三人开工步骤](docs/onboarding.md)，再进入自己的模块 README 和 TASKS。**A1 数据准备与B的Synthea训练运行已实现，分别见 [A 模块说明](src/data_evaluation/README.md)和 [SSPNet运行步骤](src/recommendation/RUNNING.md)；共享推荐接口、C及A2/A3集成待继续。

## 目录框架

```text
src/
├── data_evaluation/     A：数据、评价、集成
│   ├── configs/         已有数据准备配置
│   ├── tests/           已有A1检查，评价/集成检查后续补充
│   └── reports/         已有A1聚合报告
├── recommendation/     B：映射、药物图、SSPNet
│   ├── configs/         已有SSPNet运行配置
│   ├── tests/           已有映射、图、指标和模型检查
│   └── reports/         已有实际运行报告及聚合JSON
└── knowledge/          C：BIBM 诊断与用药核查
    ├── configs/         后端和规则加载设置，待 C 填写
    ├── prompts/         有来源的提示词，待 C 整理
    ├── rules/           带条件和审核状态的候选规则，待 C 整理
    ├── tests/           规则状态与推理检查，待 C 实现
    └── reports/         方法来源与实际运行报告，待 C 填写
```

每个模块已有 README.md（从哪里开始）、TASKS.md（具体任务与验收）、AGENTS.md（修改范围）。空目录用 .gitkeep 保留；A1 已实现，其余模块实现范围见各自 README，建议文件名不代表已实现。

目标工作链如下；A1与SSPNet适配运行已验证，公共推荐接口、知识核查和总集成仍待实现：

```mermaid
flowchart LR
    S["Demo / Synthea"] --> A["A：病例与划分"]
    A --> B["B：SSPNet 推荐"]
    B --> C["C：用药核查"]
    C --> R["A：集成、评价与报告"]
    D["DXY 问诊基线：已跑通"] --> M["C：MLN 诊断"]
```

两条链使用不同病例，不直接拼接。先验证各自模块，再评估推荐与知识核查的结合。

## 现在准备到哪里

| 内容 | 状态 |
|---|---|
| SSPNet / Diaformer 源码 | 已拉取并固定上游版本 |
| MIMIC-III Demo | 五张表可读取，覆盖 100 名患者；仅用于流程开发 |
| Synthea 合成病历 | 已下载官方历史 CSV 样本并检查：1,171 名合成患者，可用于推荐流程开发和模拟实验 |
| 药物映射、参考预处理与 DDI | 当前38类词表、EHR172边/DDI75边已生成；DDI来源逐项重建与梯度核验通过 |
| MIMIC-IV Demo / DDI外部核查清单 | 五表100人/275次原始住院尚待适配；250例清单已冻结50/5/195划分，位置与知识库基线已运行 |
| DDICorpus / DDInter / DialMed | 关系抽取数据已完整取得并训练轻量基线；DDInter七类检索已运行；DialMed dev/test已取得，推荐前输入待准备 |
| DXY / Muzhi | 已实际读取，样本数量、疾病和症状数与 BIBM 表 I 一致 |
| Synthetic 诊断集 | 文件可读取；采用现有 266 症状版本时记录与 BIBM 的差异，不等待同版本数据 |
| DXY / Diaformer 基线 | 环境、训练、问诊、保存与重载测试已通过；[结果与命令](docs/dxy-diaformer.md) |
| 后续条件 | 先用公开替代材料适配；BIBM 完整实现尚未找到，完整 MIMIC 权限未取得，不影响当前开发 |

详细数量、来源、检查范围和缺口见 [数据与代码状态](docs/resources.md)。

## 接下来做什么

A1 v3全量保留可关联就诊，主任务至少两次有效就诊、允许空操作。当前38类B数据为训练1433/验证354/测试351条；不再以旧24类筛选后的数量代表当前数据。第一批简单基线与分组结果支持继续保留空操作和一次历史样本，但不作因果或临床有效性声称。接下来A适配MIMIC-IV并申请完整库，B固定候选/编码交接，C做有来源规则及零样本核查对照；详细任务在各模块TASKS.md。真实大规模验证数据尚未取得。

| 负责人 / 目录 | 第一阶段交付 | 完成依据 |
|---|---|---|
| [A：你，@lifan25](src/data_evaluation/README.md)；src/data_evaluation/ | 病例与患者划分、统一评价、最后的调用集成；审核并合并 B/C 的 PR | 无患者交叉/未来泄漏，指标可核对，最终调用可复查 |
| [成员 B：推荐](src/recommendation/README.md)；src/recommendation/ | 药物映射、词表与图、SSPNet 适配训练和 recommend 接口 | 编码/矩阵一致，实际前向与反向、重载推理通过 |
| [成员 C：知识](src/knowledge/README.md)；src/knowledge/ | BIBM 提示词/规则流程、MLN 诊断、带来源的用药核查接口 | 实际后端调用及核查分支可复查，缺失信息不会误报为安全 |

成员 B/C 暂不绑定账号，确定后由 A 填写各模块 TASKS.md。各自的代码、测试、配置和说明放进自己的目录，公共文件由 A 维护。

从三个首项同时开始：A1 整理病例和划分；B1 检查药物映射；C1 梳理规则/提示词与推理后端。A1 合并后 B 接模型文件，B/C 接口通过后 A 做总集成。具体待办、产物和验收标准只维护在各模块 TASKS.md。

成员从 b/、c/ 分支提 PR，只改自己的模块，由 @lifan25 审核并合并，不直接推送 main。公共接口见 [protocol.md](docs/protocol.md)，完整修改范围和操作步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。

2026-11-07 已核验：仓库公开，main 已启用经典分支保护。普通成员必须通过 PR，并获得至少一次批准及 Code Owner（@lifan25）的审核；新增提交撤销旧批准，合并前必须解决讨论，禁止强推和删除。非草稿 PR 应自动请求 @lifan25 审核，CODEOWNERS 检查无错误。

管理员保留绕过权限，供 A 处理自己的维护变更；不得用它替 B/C 跳过审核。批准后谁点击合并、每人修改哪些目录仍按协作规则执行，分支保护不是目录写权限。当前没有要求自动测试状态通过，后续建立实际检查后再配置。

## 同步和检查

首次取得项目：

```powershell
git clone --recurse-submodules https://github.com/lifan25/mmagent.git
Set-Location mmagent
```

已有本地项目，在项目根目录同步：

```powershell
git pull --ff-only
git submodule update --init --recursive
```

仅检查数据，无需安装 PyTorch：

```powershell
python scripts/fetch_public_demo.py --check-only
python scripts/check_diagnosis_data.py
```

使用自己已安装的 Python 解释器。脚本只报告聚合统计，不训练、不覆盖上游数据、不输出病例内容。

下载公开合成病历并查看本地病例预览：

```powershell
python scripts/fetch_synthea_sample.py
python scripts/preview_cases.py
```

预览位于 outputs/data-preview/病例预览.md，同目录有可读 JSON。这些是源数据示例，不是模型结果；保存在本地，不提交病例。Synthea 合成实验不能代表真实临床效果；换数据本身不作为研究贡献。

## 仓库入口

- [三人开工步骤与第一批 PR](docs/onboarding.md)。
- [数据、代码、环境与缺失材料](docs/resources.md)。
- [三人修改范围、PR 操作与组长验收](CONTRIBUTING.md)。
- [DXY / Diaformer 环境、运行与结果](docs/dxy-diaformer.md)。
- [上游代码及固定版本](third_party/README.md)。
- [公开 Demo 及许可证](data/public/mimiciii-demo-1.4/README.md)。
- [数据与接口协议](docs/protocol.md)；[虚构接口示例](examples/case.synthetic.json)。
- [实验记录模板](docs/templates/experiment.md)；[规则记录模板](docs/templates/rule.md)。

SSPNet 负责推荐，Diaformer 仅是 BIBM 的问诊依赖，不是 BIBM 完整实现。原始完整 MIMIC、受控病例、权重和密钥不上传；官方公开 Demo 保留其原始来源和许可证。

