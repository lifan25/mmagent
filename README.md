# 有医学知识依据的个性化用药推荐 agent

目标：SSPNet 产生个性化候选药物，借鉴 BIBM 的知识提取与规则化方法核查结果，由 agent 组织输入检查、工具调用和展示。

第一版使用已有诊断与结构化病历。DXY/Diaformer 已完成一次150轮训练和独立测试：79/104条正确，准确率75.96%。SSPNet 已完成 Synthea v3 的20轮适配训练、验证选模、权重重载与一次测试：Jaccard79.81%、F1 83.04%；详见 [运行报告](src/recommendation/reports/sspnet-synthea-v3.md)。BIBM整体、原论文严格复现和 agent 集成仍未完成。

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
| 药物映射、参考预处理与 DDI | MoleRec 材料已保存本地；drug-DDI.csv 已下载，尚未生成与本项目词表一致的图 |
| DXY / Muzhi | 已实际读取，样本数量、疾病和症状数与 BIBM 表 I 一致 |
| Synthetic 诊断集 | 文件可读取；采用现有 266 症状版本时记录与 BIBM 的差异，不等待同版本数据 |
| DXY / Diaformer 基线 | 环境、训练、问诊、保存与重载测试已通过；[结果与命令](docs/dxy-diaformer.md) |
| 后续条件 | 先用公开替代材料适配；BIBM 完整实现尚未找到，完整 MIMIC 权限未取得，不影响当前开发 |

详细数量、来源、检查范围和缺口见 [数据与代码状态](docs/resources.md)。

## 接下来做什么

开发用原始材料已经找到。A1 v3 全量保留所有可关联就诊，至少两次有效就诊、允许空操作：Synthea为803人/2948次候选，形成2139条有历史样本；Demo为13人/41次候选、有历史样本28。本轮B精确无歧义映射到24类药物后，实际训练822/验证198/测试216条；不是全部原始处方空间。9500个当前空操作训练步骤与137条空操作测试样本均通过。真实大规模验证数据未就绪。

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

