# 有医学知识依据的个性化用药推荐 agent

目标：SSPNet 产生个性化候选药物，借鉴 BIBM 的知识提取与规则化方法核查结果，由 agent 组织输入检查、工具调用和展示。

第一版使用已有诊断与结构化病历。DXY/Diaformer 已完成一次 150 轮训练和独立测试：79/104 条正确，准确率 75.96%。BIBM 原诊断任务与新增用药核查分开验证；BIBM 整体、SSPNet 与 agent 尚未完成。

## 现在准备到哪里

| 内容 | 状态 |
|---|---|
| SSPNet / Diaformer 源码 | 已拉取并固定上游版本 |
| MIMIC-III Demo | 五张表可读取，覆盖 100 名患者；仅用于流程开发 |
| DXY / Muzhi | 已实际读取，样本数量、疾病和症状数与 BIBM 表 I 一致 |
| Synthetic | 文件可读取，但症状数量与 BIBM 表 I 不一致，暂不作首个复现数据集 |
| DXY / Diaformer 基线 | 环境、训练、问诊、保存与重载测试已通过；[结果与命令](docs/dxy-diaformer.md) |
| 正式复现条件 | 仍缺 BIBM 完整实现、SSPNet 配套材料和完整 MIMIC 权限 |

详细数量、来源、检查范围和缺口见 [数据与代码状态](docs/resources.md)。

## 接下来做什么

| 负责人 | 本轮先做的事 | 完成依据 |
|---|---|---|
| [A：数据与评估](src/data_evaluation/TASKS.md) | 用 ADMISSIONS 确认 Demo 就诊关联和时间；落实完整数据、算力与环境 | 可复查的病例组织结果、资源状态、评价约定 |
| [B：SSPNet](src/recommendation/TASKS.md) | 向老师取得预处理、映射、DDI 和附录，核对五个模型输入文件 | 每个输入文件来源明确；可执行的预处理路径 |
| [C：BIBM 与知识](src/knowledge/TASKS.md) | 验收 DXY 基线；取得 BIBM 完整代码、提示词和规则 | 基线结果可复查，原方法缺失材料落实 |

三个人直接维护各自 TASKS.md。共享接口见 [protocol.md](docs/protocol.md)，日常协作见 [CONTRIBUTING.md](CONTRIBUTING.md)。当前先做数据与模型基线。

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

## 仓库入口

- [数据、代码、环境与缺失材料](docs/resources.md)。
- [DXY / Diaformer 环境、运行与结果](docs/dxy-diaformer.md)。
- [上游代码及固定版本](third_party/README.md)。
- [公开 Demo 及许可证](data/public/mimiciii-demo-1.4/README.md)。
- [数据与接口协议](docs/protocol.md)；[虚构接口示例](examples/case.synthetic.json)。
- [实验记录模板](docs/templates/experiment.md)；[规则记录模板](docs/templates/rule.md)。

SSPNet 负责推荐，Diaformer 仅是 BIBM 的问诊依赖，不是 BIBM 完整实现。原始完整 MIMIC、受控病例、权重和密钥不上传；官方公开 Demo 保留其原始来源和许可证。

