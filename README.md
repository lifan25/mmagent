# 有医学知识依据的个性化用药推荐 agent

目标：SSPNet 产生个性化候选药物，借鉴 BIBM 的知识提取与规则化方法核查结果，由 agent 组织输入检查、工具调用和展示。

当前主线已可运行：结构化病例 → SSPNet真实推荐 → 有来源规则核查 → 返回候选、核查依据和补信息需求。新增RxNorm原码推荐已完成训练及对照，核查已有有限实际执行；下一步重点是患者事实与规则覆盖、独立核查参考。零样本和DialMed延后。推荐与规则执行不依赖语言模型服务。

最新已完成[独立核查数据准备](src/data_evaluation/reports/medpic-readiness-20261114.md)：取得作者公开MedPIC 467道模拟患者用药题，固定20题/100选项的无答案输入和B/C空标注包，6项相关测试通过。AI题意初审17题适合避药、2题剂量范围外、1题待确认；现有冻结产品规则无法直接执行，尚无新增核查准确率或双人人审。任务、来源边界、分工已写入各模块TASKS和[C标注协议](src/knowledge/MEDPIC_ANNOTATION.md)，[运行步骤](src/data_evaluation/RUNNING.md#medpic独立核查开发准备)可重建。未新增模型；原195条DDI确认集仍封存，MedPIC余447题暂不称独立测试。

最新核查实验已完成：新增有出处的年龄/CAD事实、少量精确来源规则，固定推荐做四分支对照，并建立执行前冻结的40条独立角色来源参照。参照40/40一致、82项相关单元检查通过；**实际覆盖仍为2/344，未提高**。新状态244条未覆盖、98条条件不足、2条完成单规则；没有用缺失记录填阴性或添加新模型。完整负结果与范围计数修正见[核查覆盖报告](src/data_evaluation/reports/check-coverage-20261114.md)，运行见[A说明](src/data_evaluation/RUNNING.md#来源范围v2与独立编写参照)。来源参照不是专家临床金标准。

SSPNet新增72个原始RxNorm标签（69完整制剂、2包装、1成分规格），使用原患者划分完成20轮CPU训练，验证选第16轮；全351条测试Jaccard65.30%、F1 71.05%。同344条支持病例上，原码F1为72.49%，高于“旧类别＋训练众数药品”的60.58%；投影回共同ATC3后F1为81.71%与80.91%。这些是单种子合成队列探索结果，不能跨标签空间直接比原始分数。见[新训练报告](src/recommendation/reports/sspnet-synthea-rxnorm-v5.md)与[集成及对照报告](src/data_evaluation/reports/rxnorm-agent-20261114.md)。旧38类[权重和结果](src/recommendation/reports/sspnet-synthea-product-v4.md)保留；[DDI溯源与诊断](src/recommendation/reports/ddi-audit-20261114.md)仍适用其历史范围。

新版本仍支持344/351条输入，7条明确拒绝；公开接口全部72维分数与训练保存结果完全相同。原自动规则2条启用、1条拒绝，本轮补官方产品适用范围及真实同次事实：可执行规则从0增至2次，均为二甲双胍肾功能核查、无警告；95条仍缺条件、247条未覆盖。**2条完成单规则不代表整处方已核查。**廉价类别众数对照可执行4次规则，因此不声称新模型核查覆盖更高。90项测试通过。DXY/BIBM受限条件MLN仍为47/104（45.19%），低于Diaformer的79/104（75.96%）；原方法缺口及旧38类集成见[历史报告](src/data_evaluation/reports/agent-integration-20261114.md)。

研究阶段先看[当前研究设计（含零样本对照）](docs/research-design.md)和[MIMIC-IV本人申请步骤](docs/mimic-access.md)。现有Synthea测试已用于错误分析，作为探索性结果；正式确认需未参与开发的真实数据。

已取得DDICorpus-2013、DDInter七分类和DialMed的dev/test，早期探索见[新数据与实验报告](src/knowledge/reports/open-data-pilot-20261114.md)。这些补充数据不替代纵向主队列。Qwen量化权重已完整校验并用CPU完成本次知识提取，服务随后关闭；未新增CUDA，零样本病例实验未启动。

**刚拉取仓库：先看 [三人开工步骤](docs/onboarding.md)，再进入自己的模块 README 和 TASKS。**最小调用入口见[运行步骤](src/data_evaluation/RUNNING.md)。病例、处理数据和模型权重不随Git克隆取得，需按模块说明重建或在许可范围内交接；不必重复训练已有可核对的本地产物。

## 目录框架

```text
src/
├── data_evaluation/     A：数据、评价、集成
│   ├── configs/         已有数据准备配置
│   ├── tests/           病例、划分和集成检查
│   └── reports/         数据及agent集成聚合报告
├── recommendation/     B：映射、药物图、SSPNet
│   ├── configs/         已有SSPNet运行配置
│   ├── tests/           已有映射、图、指标和模型检查
│   └── reports/         已有实际运行报告及聚合JSON
└── knowledge/          C：BIBM 诊断与用药核查
    ├── configs/         已有实验设置
    ├── prompts/         固定版本知识提取提示词
    ├── rules/           来源、模型原始规则与审核状态
    ├── tests/           条件、未知状态与MLN数学检查
    └── reports/         方法来源与实际运行报告
```

每个模块已有 README.md（从哪里开始）、TASKS.md（具体任务与验收）、AGENTS.md（修改范围）。已有代码的交付范围和未完成部分见各自README及TASKS。

以下两条最小工作链均已运行；用药核查覆盖与诊断效果的限制见集成报告：

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
| 药物映射、参考预处理与 DDI | 新72原码词表、EHR254边/DDI7边已生成；46/72原码完整连接CID。旧38类图保留，两个DDI率不能直接比较安全性 |
| MIMIC-IV Demo / DDI外部核查清单 | 五表100人/275次原始住院尚待适配；250例清单已冻结50/5/195划分，位置与知识库基线已运行 |
| DDICorpus / DDInter / DialMed | 关系抽取数据已完整取得并训练轻量基线；DDInter七类检索已运行；DialMed dev/test已取得，推荐前输入待准备 |
| MedPIC-Bench | 作者公开467题及外部答案已在本地；固定20题开发输入、B/C盲模板就绪，尚待真实人审与成分级规则适配 |
| DXY / Muzhi | 已实际读取，样本数量、疾病和症状数与 BIBM 表 I 一致 |
| Synthetic 诊断集 | 文件可读取；采用现有 266 症状版本时记录与 BIBM 的差异，不等待同版本数据 |
| DXY / Diaformer 基线 | 环境、训练、问诊、保存与重载测试已通过；[结果与命令](docs/dxy-diaformer.md) |
| 后续条件 | 先用公开替代材料适配；BIBM 完整实现尚未找到，完整 MIMIC 权限未取得，不影响当前开发 |

详细数量、来源、检查范围和缺口见 [数据与代码状态](docs/resources.md)。

## 接下来做什么

A1 v3全量保留可关联就诊，主任务至少两次有效就诊、允许空操作。新72原码数据为训练1433/验证355/测试351条，恢复旧映射曾删除的1条验证，词表外目标计漏报。事实盘点、少量来源规则和独立编写参照已完成，覆盖仍低。下一步按已准备的MedPIC 20题开发包开展B/C独立输入审阅和逐条来源复核，A收回记录、处理分歧并固定可执行评价；缺少相应测量和明确阴性事实时，不继续按旧测试补规则。B复核未见目标及26个不完整CID连接；BIBM原方法缺口与低分结果保留。真实大规模数据申请可并行。

| 负责人 / 目录 | 第一阶段交付 | 完成依据 |
|---|---|---|
| [A：你，@lifan25](src/data_evaluation/README.md)；src/data_evaluation/ | 病例与患者划分、统一评价、最后的调用集成；审核并合并 B/C 的 PR | 无患者交叉/未来泄漏，指标可核对，最终调用可复查 |
| [成员 B：推荐](src/recommendation/README.md)；src/recommendation/ | 药物映射、词表与图、SSPNet 适配训练和 recommend 接口 | 编码/矩阵一致，实际前向与反向、重载推理通过 |
| [成员 C：知识](src/knowledge/README.md)；src/knowledge/ | BIBM 提示词/规则流程、MLN 诊断、带来源的用药核查接口 | 实际后端调用及核查分支可复查，缺失信息不会误报为安全 |

成员 B/C 暂不绑定账号，确定后由 A 填写各模块 TASKS.md。各自的代码、测试、配置和说明放进自己的目录，公共文件由 A 维护。

接手时先复核各自已交付产物：A看351条输入的分母与状态，B看权重/词表一致性和7条未支持输入，C看来源、拒绝规则及条件缺失。具体待办、产物和验收标准只维护在各模块TASKS.md。

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

