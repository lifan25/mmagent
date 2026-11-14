# B：SSPNet 推荐模块

负责人：成员 B，账号待 A 指定。任务状态只更新 [TASKS.md](TASKS.md)，公共修改与 PR 规则见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

2026-11-14新增原RxNorm药品标签v5：72个训练标签，全部1433/355/351病例保留；新训练与严格评价说明见 [RUNNING第9节](RUNNING.md#9-原始rxnorm药品标签v5)和[v5报告](reports/sspnet-synthea-rxnorm-v5.md)。原38类默认接口与历史产物继续保留，新模型需显式选择独立检查点。

EHR 是电子健康记录，DDI 是药物相互作用；这里的两种图分别表示药物在记录中共同出现，以及外部数据记录的药物相互作用。它们的节点必须对应同一药物词表。

## 先从这里开始

1. 阅读 [三人开工步骤](../../docs/onboarding.md) 和 [资源清单](../../docs/resources.md)，确认自己的电脑取得了映射与 DDI 文件。
2. 阅读 SSPNet 的 README、src/main.py、src/training.py 和 src/modules/MoleRec.py，画清加载数据到 forward 的调用关系。
3. 阅读 MoleRec 的 processing.py，区分药物编码转换、词表、病例序列、EHR 图和 DDI 图。
4. 当前已有 Synthea v3 的映射/构图、原模型适配和实际训练入口，先按 [RUNNING.md](RUNNING.md) 核验环境与运行；继续扩展前检查映射覆盖和适配差异，不重新实现一套相同程序。

## 本目录结构

```text
recommendation/
├── AGENTS.md      修改边界
├── README.md      模块导航和使用说明
├── TASKS.md       任务、进度、证据与交接
├── configs/      映射、构图与训练配置
├── tests/        词表、图、推理契约与重载检查
└── reports/      映射覆盖与实际运行的聚合报告
```

当前已实现 prepare.py、model.py、train.py、predict.py，原 SSPNet 仍在 third_party/SSPNet/，未修改子模块。`SSPNetRecommender.score_case(case)`默认加载旧38类，显式指定独立检查点可加载已训练的72原始RxNorm标签模型；两者均已接入A/C。用法见 [RUNNING.md第8节](RUNNING.md#8-共享case推理与交接不重训)和[第9节](RUNNING.md#9-原始rxnorm药品标签v5)。这是 Synthea 药物空间适配，不是原论文数据的严格复现。

早期24类版本完成过20轮训练、验证选模、保存重载和最终测试：216条测试样本的Jaccard79.81%、F1 83.04%，其中137条当前操作为空的样本均正常完成。该历史结果见 [实际运行报告](reports/sspnet-synthea-v3.md)及[聚合JSON](reports/sspnet-synthea-v3-results.json)；当前默认推理使用38类新版，不加载24类权重。

## 实现与后续接口

| 文件 | 建议职责 |
|---|---|
| prepare.py（已实现） | 旧版RxCUI → 无歧义ATC第三级类别；v5保留原始RxCUI；生成对应训练词表、EHR/DDI图和病例；NDC输入尚未实现 |
| model.py（已实现） | 正常导入原模型的继承适配；禁用诊断绘图，明确初始化和调用参数 |
| train.py（已实现） | 实际训练、验证选模、保存并重载、最终测试及空操作分组统计 |
| predict.py（已实现） | 默认缓存加载旧38类模型，也支持显式加载72原始RxNorm标签检查点；严格编码共享Case，输出recommend(case)与独立全词表分数 |
| verify_predict.py（已实现） | 旧38类固定测试分数同值核验、原始Case与既有编码对照和本地交接；v5证据与统一评价入口见RUNNING第9节 |

药物映射与 prepare.py 合并。推理读取同版 `mapping-decisions.json`，不重新查询或选择映射。公共接口实现现有 `0.1-draft`，协议仍待三人正式冻结；agent整体由A集成、评价，B只提供候选与分数。

## 输入和输出

| 方向 | 内容 | 放在哪里 |
|---|---|---|
| 读取 | A 的原始编码病例、患者划分和 manifest | data/processed/data_evaluation/<数据集与版本>/ |
| 读取 | MoleRec 映射、DDI 文件及原来源/许可证 | data/reference/，原始文件只读 |
| 本地生成 | 模型记录、词表、EHR/DDI 图和版本清单 | data/processed/recommendation/<数据集与版本>/ |
| 交给 A | 同词表全药物分数、预测、标准答案、阈值及未支持样本统计 | outputs/recommendation/，本地 |
| 交给 C | system/code 的准确含义、药物层级、映射覆盖和不支持项 | 本模块 reports/ 的汇总说明；病例不提交 |
| 对外调用 | Recommendation，包含模型/词表版本与候选 | 遵守 [共享协议](../../docs/protocol.md) |

预测输入中不能包含当前药物答案；训练使用的监督标签与推理字段分开。全词表评价产物的交接约定见 [协议第 9 节](../../docs/protocol.md#9-开发交接文件约定草案)。

## 配置和检查建议

- configs/：输入 manifest、数据集、编码层级、映射规则、DDI 筛选、隐藏维度、学习率、批次、种子、模型保存路径。论文参数与实际采用值分列。
- tests/：编码一致性、一对多/未匹配映射、图节点顺序/维度/对称性、未知编码、输入不含答案、实际前向反向、保存重载。
- reports/：映射覆盖按“不同药物数”和“处方行数”分别报告；训练报告写实际命令、loss、耗时、设备和是否完成重载。

## 最影响结果的几个建议

1. 先固定“一个模型输出编号代表什么”。成分和药物类别不同，不能把某成分规则直接用于整个类别；不要为了对上论文而硬凑 131 个编号。
2. 用一个数据集先跑通。本阶段以 Synthea 模拟开发为主，Demo 用于 MIMIC 字段/映射检查；Synthea 是 RxNorm，不能直接当作 NDC 使用。
3. 词表、图、权重必须配套。不能把其他仓库同名 pkl 直接拼起来；EHR 共现图只取训练数据，外部 DDI 来源与筛选另外固定。
4. 先实际跑通一个批次，再做长训练。公开训练调用和 forward 参数数量不一致，需要适配；ddi_mask_H 的用途先核对，不能仅为消除报错塞入任意矩阵。
5. B 负责产生分数，A 负责统一评价。先用手算样例核对口径，再报告正式结果；不要用测试分数反复选阈值。

## 实际运行与验收

完整步骤见 [RUNNING.md](RUNNING.md)。依赖安装用 setup_environment.ps1；数据准备运行 prepare.py，训练/重载/最终评价运行 train.py；两个入口均支持 --config。其输出目录非空时拒绝覆盖，重跑使用独立版本目录。

旧配置的源数据是 A1 Synthea v3 的2139个有历史样本。旧映射排除无匹配、多类别歧义及空目标/无已知药物历史后，实际训练822条、验证198条、测试216条，不能将其分数当成全部原始处方准确率。旧词表为96个诊断/62个操作（各含内部UNK）及24个ATC第三级药物类别。

历史24类版本的当前操作为空样本：训练475条、验证123条、测试137条；含空操作历史的样本分别为724/170/200。这些数量不是38类或v5当前队列统计。当前药物只作为目标，不传入模型输入；预测与病例标识仅保存在本地。

2026-11-07映射复核：产品级映射恢复至38类、训练1433/验证354/测试351条。新配置、完整依据与DDI未覆盖范围见[映射复核](reports/mapping-coverage.md)和[运行说明](RUNNING.md)。新版已完成20轮完整训练，测试Jaccard74.65%、F1 80.91%、AP89.44%；DDI率47.30%，尚未达到低冲突目标。详见[新版结果](reports/sspnet-synthea-product-v4.md)，旧版20轮结果保留作历史对照。

2026-11-14已完成[DDI溯源与第一批对照](reports/ddi-audit-20261114.md)：75条类别边重建一致，概率外积/梯度正确；47.30%是选定图在CID可映射对上的标记比例，不能直接解释成临床风险。新增历史、频次基线和分组结果支持继续保留空操作与一次历史样本。零样本核查与直接推荐纳入[研究设计](../../docs/research-design.md)，其运行状态以C模块记录为准；B的后续具体交付见TASKS.md。

同日完成[共享推理接口核验](reports/predict-interface-20261114.md)：351条旧编码预测逐位一致；严格公共接口支持344条原始Case，明确拒绝7条未知诊断/操作病例，未静默送入UNK。344条支持病例的编码与原产物一致，其中211条当前操作为空。当前用药答案不进入模型；历史RxNorm映射与输出ATC3类别层级可追溯。

同日后续v5已完成独立20轮训练和351条公开接口核验，344条支持病例的72维分数与保存值逐位相等。A加入有来源的同次上下文后，2条病例各执行一条二甲双胍规则、0警告，尚不能说明整份处方安全或优于廉价对照；见[v5报告](reports/sspnet-synthea-rxnorm-v5.md)与[A统一报告](../data_evaluation/reports/rxnorm-agent-20261114.md)。
