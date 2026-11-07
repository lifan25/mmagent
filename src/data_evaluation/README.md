# A：数据、评价与集成模块

负责人：@lifan25。任务状态只更新 [TASKS.md](TASKS.md)，本文件说明模块结构与交接方式。

## 先从这里开始

1. 阅读 [三人开工步骤](../../docs/onboarding.md)、[资源清单](../../docs/resources.md)。
2. 打开 MIMIC Demo 的五张表和 Synthea 的六张表，区分患者、就诊、编码和监督答案。
3. 阅读 [共享协议](../../docs/protocol.md)，先做 A1 的病例组织，不等待模型实现。
4. 第一批只交病例组织和划分；A2 的指标、A3 的集成分别交付。

## 本目录结构

```text
data_evaluation/
├── AGENTS.md      修改边界
├── README.md      模块导航和使用说明
├── TASKS.md       任务、进度、证据与交接
├── configs/      日后放数据选择、划分、筛选配置
├── tests/        日后放小样例和指标检查
└── reports/      日后放可提交的聚合统计与验收报告
```

当前 A1 全量实现已通过本机核验：支持 Demo/Synthea 就诊关联、审计、筛选、患者划分和独立标签的预测样例；单患者教学入口保留。A2/A3 尚未实现。实际统计见 [data-summary.md](reports/data-summary.md)。

## 实现文件与后续计划

| 文件 | 建议职责 | 不承担什么 |
|---|---|---|
| prepare.py、cohort.py（A1 已实现） | 全量病例、审计、筛选、患者划分；保留单患者入口 | 不负责药物映射和模型整数词表 |
| evaluate.py（待创建） | 读取标准答案与全词表分数，计算统一指标 | 不训练模型、不根据测试结果选阈值 |
| pipeline.py（待创建） | 校验输入、调用 B 推荐和 C 核查、组织结果 | 不复制 B/C 的实现，不训练时临时编造规则 |

文件名是拆分建议；若发现合并文件更清楚，可以先在 TASKS.md 说明。不要仅为目录齐全创建空 Python 文件。

## 输入和输出

| 方向 | 内容 | 放在哪里 |
|---|---|---|
| 读取 | Demo/Synthea 原表及来源版本 | data/public/、data/local/，原始文件只读 |
| 交给 B | 原始编码病例、患者级划分、筛选统计和 manifest | data/processed/data_evaluation/<数据集与版本>/，本地 |
| 接收 B | 词表/图标识、预测分数、标准答案对齐方式 | B 的本地产物；按共享协议核对 |
| 接收 C | CheckReport 及规则来源、覆盖范围 | 函数返回或本地输出 |
| 交给全组 | 聚合人数/就诊数、指标口径、完整运行步骤 | 本目录 reports/ 和 README.md |

manifest 是描述数据来源和版本的清单，字段建议见 [协议第 9 节](../../docs/protocol.md#9-开发交接文件约定草案)。真实患者 ID、病例和划分清单留在本地；PR 报告只提交聚合统计。

## 配置和报告建议

- configs/：数据集名称、原表路径、输出路径、筛选条件、随机种子、患者划分比例；不要写他人的绝对路径或密钥。
- tests/：至少覆盖患者不交叉、历史时间早于当前、当前药物不进入输入、重复编码去重、未知与空值区别、手算指标。
- reports/：每次报告列命令、配置版本、输入版本、实际统计、检查结果、剩余问题；复用 [实验模板](../../docs/templates/experiment.md)。

## 技术建议

先用 Demo 核对关联和字段，再把相同组织流程适配到 Synthea；两者独立输出。小样本用于流程检查，首轮推荐模拟实验优先使用 Synthea，不同时开展两套大规模训练。

先从源记录中明确记载的事实开始。Synthea 的慢性病延续、同日多次就诊和药物持续时间都可能改变样本定义，先写清选择再实现。A 的划分完成后 B 还会做映射筛选，需保留原始划分并统计变化，不重新按结果挑患者。

指标的计算方式先固定，再接模型输出。集成阶段先用仓库里的 [虚构 Case](../../examples/case.synthetic.json)、[Recommendation](../../examples/recommendation.synthetic.json)、[CheckReport](../../examples/check.synthetic.json) 对齐字段；这些样例不能计入模型指标。

## A1 全量运行

在项目根目录执行（仅使用 Python 标准库）：

```powershell
.venv\Scripts\python.exe src/data_evaluation/prepare.py --dataset all
.venv\Scripts\python.exe -m unittest discover -s src/data_evaluation/tests -v
```

其他电脑用自己的 Python 解释器。可单选 --dataset mimic 或 --dataset synthea；--config 可指定 JSON 配置，默认 configs/preparation.json。路径相对仓库根目录。v3 全量层保留全部能关联的就诊；主任务候选默认 seed=8、4:1:1、诊断与药物非空、每人至少两次有效就诊，允许空操作集合，源表不修改。空操作的实际模型路径核验见 [报告](reports/empty-procedures.md)。require_procedures=true 可恢复严格条件供对照，但应换用独立输出目录。

输出目录已存在且非空时拒绝覆盖。重跑请复制配置并改为新版本输出目录，再用 --config 指定。相同源数据、规则和种子得到相同患者划分。

每套数据输出至 data/processed/data_evaluation/<数据集与版本>/：

| 文件 | 内容 |
|---|---|
| visits.jsonl | 全量可关联就诊，保留单次就诊、缺失/无效时间和原始药物记录；未分配主任务集合 |
| visits.audit.jsonl | 与 visits.jsonl 相同的全量审计别名，兼容先前读取方式 |
| main_visits.jsonl | 至少两次有效就诊患者的有效学习记录，含当前药物监督答案及集合归属 |
| split.json | 主任务候选患者的训练、验证、测试清单，本地保存；不覆盖全量层单次患者 |
| prediction_examples.jsonl | 所有主任务候选就诊的 case/target，保留未知历史样例供无历史适配 |
| main_prediction_examples.jsonl | 主任务实际预测样本：至少有一次已结束且含可用药物历史的就诊，标签单独保存 |
| manifest.json | 来源、配置、代码提交及脏工作区标记、规则和统计 |
| summary.json | 聚合统计 |

训练/验证患者数按比例向下取整，其余归测试；至少三名患者但出现空集时，显式调整为验证/测试各一人、其余训练，标记 small_sample_split_adjustment。不足三人直接报错。

空代码和 0 不加入正常代码集合，原始药物记录和无效行数保留；此处不做 NDC/RxNorm → ATC 映射。跨患者关联、重复主键、缺表头报错；孤立明细单独计数。空集合只表示源表没有匹配记录，不证明临床上不存在。

历史只取同患者筛选后已经结束且严格早于当前开始的就诊，并排除日期未知/不早于当前的历史药物记录。history=null 表示未取得符合条件的历史。过敏、肾功能保持未知，不做慢性病跨就诊补全。任务是回顾性就诊集合预测，当前诊断/操作被视为可用，不代表入院时已获知所有信息。

真实 Demo 沿用 restricted 的真实病例处理模式，许可仍为官方公开 Demo 的 ODbL；该字段不表示 Demo 需要访问审批。所有病例、划分、预测样例均被 Git 忽略。

v3 采用独立输出目录，保留 v1/v2 结果供对照。10059 的两次住院均保留，并进入两次就诊主任务候选；其中第二次可形成一条有历史预测样本。单次患者保留于全量层，后续无历史对照需先检查模型支持并制定与当前患者归属兼容的划分，不自动混入本次主任务。

空操作保留为 procedures=[]，context.procedure_record_status 标为 not_recorded；有编码则为 recorded。不代表已确认患者未接受操作，也不为模型虚构操作代码。历史同样保留空集合。A1 的11个标准库测试与模型核验是两套检查；后者需单独执行 probe_empty_procedures.py，使用已有 PyTorch/NumPy，不要求数据读取阶段安装模型依赖。

B 应读取 main_visits.jsonl/split.json 生成模型词表与图，使用 main_prediction_examples.jsonl 做有历史任务。主任务候选的第一条或重叠就诊未必有可用历史，不能把所有候选就诊数当作有历史预测样本数。公开 SSPNet eval_one_epoch 仍有 len(input_seq)<3 的跳过条件，B 必须按新任务显式适配，记录与原公开评估方式的差异，不能直接照搬后悄悄漏评两次就诊患者。

## 单患者教学入口

在项目根目录，用可用 Python 运行（仅使用标准库，无需安装 PyTorch）：

```powershell
.venv\Scripts\python.exe src/data_evaluation/prepare.py --patient-id 10059
.venv\Scripts\python.exe -m unittest discover -s src/data_evaluation/tests -v
```

其他电脑将 .venv\Scripts\python.exe 替换为自己的 Python 解释器。

输出为 outputs/data_evaluation/patient-10059.json，本地保存、不提交 Git。已核验顺序 142582 → 122098，诊断/操作/处方原始行数分别为 9/2/25、14/8/70；三个虚构记录测试通过。

这是 patient-preview-v1 教学格式，尚不是共享协议的最终 visits/Case：diagnosis_codes、procedure_codes 为去重编码，source_records 保留三类完整明细。处方暂不映射、不去重，NDC=0 等原始值保留；空集合只表示本源表中没有匹配记录，不表示临床上确认无相关情况。本步骤未构造历史推理输入，visit_index 只表示排序，不证明所有历史事实当时已可用。
