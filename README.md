# 有医学知识依据的个性化用药推荐 agent

目标：SSPNet 产生个性化候选药物，借鉴 BIBM 的知识提取与规则化方法核查结果，由 agent 组织输入检查、工具调用和展示。

第一版使用已有诊断与结构化病历。DXY/Diaformer 已完成一次 150 轮训练和独立测试：79/104 条正确，准确率 75.96%。BIBM 原诊断任务与新增用药核查分开验证；BIBM 整体、SSPNet 与 agent 尚未完成。

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

开发用原始材料已经找到，模型输入还未生成；真实大规模验证数据未就绪。可以现在开始分工，不等待原作者完全相同的数据版本。

| 负责人 / 目录 | 第一阶段交付 | 完成依据 |
|---|---|---|
| [A：你，@lifan25](src/data_evaluation/TASKS.md)；src/data_evaluation/ | 病例与患者划分、统一评价、最后的调用集成；审核并合并 B/C 的 PR | 无患者交叉/未来泄漏，指标可核对，最终调用可复查 |
| [成员 B：推荐](src/recommendation/TASKS.md)；src/recommendation/ | 药物映射、词表与图、SSPNet 适配训练和 recommend 接口 | 编码/矩阵一致，实际前向与反向、重载推理通过 |
| [成员 C：知识](src/knowledge/TASKS.md)；src/knowledge/ | BIBM 提示词/规则流程、MLN 诊断、带来源的用药核查接口 | 实际后端调用及核查分支可复查，缺失信息不会误报为安全 |

成员 B/C 暂不绑定账号，确定后由 A 填写各模块 TASKS.md。各自的代码、测试、配置和说明放进自己的目录，公共文件由 A 维护。

从三个首项同时开始：A1 整理病例和划分；B1 检查药物映射；C1 梳理规则/提示词与推理后端。A1 合并后 B 接模型文件，B/C 接口通过后 A 做总集成。具体待办、产物和验收标准只维护在各模块 TASKS.md。

成员从 b/、c/ 分支提 PR，只改自己的模块，由 @lifan25 审核并合并，不直接推送 main。公共接口见 [protocol.md](docs/protocol.md)，完整修改范围和操作步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。

当前私有仓库套餐限制了分支保护与 CODEOWNERS：审核文件已准备，尚不能技术上强制禁止直推或强制组长批准。先手动选择 @lifan25 审核并遵守上述约定；不因此公开仓库或开通费用。

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

- [数据、代码、环境与缺失材料](docs/resources.md)。
- [三人修改范围、PR 操作与组长验收](CONTRIBUTING.md)。
- [DXY / Diaformer 环境、运行与结果](docs/dxy-diaformer.md)。
- [上游代码及固定版本](third_party/README.md)。
- [公开 Demo 及许可证](data/public/mimiciii-demo-1.4/README.md)。
- [数据与接口协议](docs/protocol.md)；[虚构接口示例](examples/case.synthetic.json)。
- [实验记录模板](docs/templates/experiment.md)；[规则记录模板](docs/templates/rule.md)。

SSPNet 负责推荐，Diaformer 仅是 BIBM 的问诊依赖，不是 BIBM 完整实现。原始完整 MIMIC、受控病例、权重和密钥不上传；官方公开 Demo 保留其原始来源和许可证。

