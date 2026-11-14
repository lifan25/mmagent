# 无需申请数据的第一批实验

日期：2026-11-14。本批按用户要求暂不依赖完整MIMIC申请。评价协议见[协议10.1](../../../docs/protocol.md#101-无需申请数据的首批实验推理前约定)。只报告实际完成的步骤；探索性结果不代表两篇原论文复现完成。

## 1. 新数据与任务边界

**DDICorpus-2013**已完整下载，作者仓库提交`819b0fa538ed83ab2a8b4f5417bba3c03249b7f3`，原ZIP与CC BY-NC 4.0许可声明保持本地。正式关系抽取训练集27,792药对（4,021正例），测试集5,716药对（979正例）。另一个DrugNER测试目录的false标签是实体识别任务占位，未混入关系抽取负例。1条训练正例缺关系类型，本次二分类仍保留。[作者数据](https://github.com/isegura/DDICorpus)、[任务论文](https://aclanthology.org/S13-2056/)。

它支持从文本识别关系，接近BIBM知识抽取的一部分；不是纵向患者数据，文本未表达交互不等于两药临床无交互。关系类型原标签写作`advise`，没有擅自更改成另一套分类。

**DDInter**官方提供八类CSV，许可CC BY-NC-SA 4.0。本次取得并冻结A/B/D/H/L/P/V七类，缺R（官方连接持续失败），共191,820行、146,518个去重无序ID药对。CSV只有药物ID、药名和Level，不含网站展示的机制原文。作为独立检索证据库，不能把未收录当阴性，也不将其Level直接映射成LexiDrug的C/D/X。[下载页](https://ddinter.scbdd.com/download/)、[条款](https://ddinter.scbdd.com/terms/)。

**DialMed**已找到作者数据，固定提交`4cd19719ad8a25e0d2cb411cdede3aea9d9e095f`，根MIT许可。已取得dev的1,192条、test的1,199条和70药标签及附录；train尚未完整下载。现有文件已足以准备零样本评价，不必等训练集，但严格推荐前输入仍待实现。原任务为对话与人工诊断到70类药物，不能替代SSPNet纵向住院任务。本轮未运行其模型实验。[作者仓库](https://github.com/f-window/DialMed)、[论文](https://aclanthology.org/2022.coling-1.60/)。

作者把医生推荐的药名替换为MASK并删除后续对话，但推荐句仍提供药物数量、用法等线索。后续若做严格推荐前任务，应从第一条匹配`\[MASK\b`的话语起整句截断，不输入`label/disease/original_dialog`；缺边界或空前缀另计，不能回退到完整对话。这是新的输入协议，不与原DDN结果直接比较；仅三个训练样例核查尚不能保证全数据没有未遮蔽处方。

本轮还核查了[EHRSHOT](https://github.com/som-shahlab/ehrshot-benchmark)，其真实纵向数据需研究使用协议，未纳入无需本人申请的路线。没有为取得真实病例寻找绕过授权的镜像。

## 2. 文本关系抽取：已完成轻量训练基线

固定seed20261114，按原药对ID排序后，从官方训练取5对仅检查格式，从正式测试均匀抽80对，不按标签平衡。80对来自47份文档，有16正、64负；与训练的完全相同句子、完全相同药对输入交集均为0。原训练有714份文档，其中624份包含本次使用的药对。

TF-IDF（二元词组、min_df=2、最多40,000特征）＋逻辑回归（C=1、balanced、liblinear），仅拟合官方训练的27,792药对，阈值固定0.5，不搜索参数。实际35,877特征，7次迭代，训练及预测约1.71秒。

| 方法 | TP | FP | TN | 阳性召回 | 阳性F1 | 全样本准确率 |
|---|---:|---:|---:|---:|---:|---:|
| 恒为文本未表达关系 | 0 | 0 | 64 | 0% | 0% | 80% |
| 恒为有交互关系 | 16 | 64 | 0 | 100% | 33.33% | 20% |
| 固定句子关键词 | 11 | 51 | 13 | 68.75% | 28.21% | 30% |
| TF-IDF＋逻辑回归（有监督） | 10 | 20 | 44 | 62.50% | 43.48% | 67.50% |

负例占80%，因此只看准确率会偏爱恒阴性；最终对照必须同时给阳性F1与识别负例的能力。未知/无效输出不从总分母删除。同文档药对相关，本批不作独立样本显著性声称。

本地产物：`outputs/knowledge/ddicorpus-tfidf-v1/`，含真实权重、分数与聚合结果。它是有任务训练的廉价参照，不是零样本方法，也不是原论文模型。

## 3. 药物清单：发现并修正位置捷径

沿用固定版本LLM-Uncertainty-DDI的250份清单，冻结50例pilot、5例格式开发、195例封存。严格大小写/空白规范化后pilot有49例能将参考药名对齐到输入槽位，1例涉及`Hydrocortisone IV`与`hydrocortisone`差异；不按结果加入别名或删除病例。

在大模型运行之前，first-two基线发现原序49/49可评分参考都对应前两个非空药物槽。它只看位置就能满分，原输入不适合证明模型具备药理知识。

修正为独立v2：对每例以seed20261114+原行号打乱非空药物，评价端同步标签，模型看不到原位置。原剂量字符串也保留原顺序，未建立可靠逐药解析，因此本批统一去掉剂量。这是**药名-only变体**，不是原含剂量设置。仅改变输入协议，不换pilot、不按模型效果挑置换。

| 位置基线 | 可评分正确数 | 命中率 | 全50条已确认命中比例 |
|---|---:|---:|---:|
| 原顺序前两个药物 | 49/49 | 100% | 98% |
| 固定置换后前两个药物 | 8/49 | 16.33% | 16% |

两者都回答50例，均无格式错误；均匀随机选药对的可评分期望约15.03%。v1和v2均保留本地。以上不是大模型结果；这次发现也意味着当前pilot参与了设计，不能称最终未见验证集。

## 4. 零样本与知识库评价入口

固定模型Qwen3-4B-Instruct-2507的Q4_K_M量化；具体修订、运行器和本机验证见[本地环境](../LOCAL_INFERENCE.md)。本阶段不改原SSPNet/Diaformer环境，不使用付费API。

`run_local_pilot.py`只向127.0.0.1发送白名单输入字段，保留原始响应、完成原因、token和时延。关系标签、参考药对、Classification不进入提示。两份无示例提示词在prompts/；先检查格式，再对冻结pilot运行，不用错误案例反复改提示词。

DDInter基线仅做精确名称映射，最高等级唯一才输出；最高并列、未知或无可排名关系则拒答。输出只表示“已检索证据中的最高对”，不代表全清单所有未知药对已排除。

在产生结果前，因R文件无法取得，将本批范围明确改为冻结七分类的partial探索实验；默认完整模式仍保留八文件门槛。实际结果：

| 指标 | 计数/比例 |
|---|---:|
| 全部清单 / 参考可评分 | 50 / 49 |
| 明确回答 / 未知 | 16 / 34 |
| 参考药对命中 / 可评分 | 12/49 = 24.49% |
| 明确回答覆盖率 | 16/50 = 32% |
| 已回答中的参考命中 | 12/16 = 75% |
| 全清单已确认命中比例 | 12/50 = 24% |

213次药名出现中177次精确唯一匹配，36次未匹配。352个待查药对中17个有可排名等级、44个Level Unknown、178个不在快照、113个涉及未匹配药名。未知全部保留，没有伪装成无冲突；等级冲突为0。

75%只描述已回答的16例，不能与100%覆盖的位置基线直接比较后声称更优。缺R可能改变映射、排序与拒答；其他预测药对未命中参考，也不证明其临床上错误。这批数据没有阴性清单，不能估计清单级误报率。

本轮已确认轻量训练、位置基线和DDInter七分类检索结果；[聚合JSON及来源](open-data-pilot-20261114.json)只含统计，不含逐例预测。大模型与CUDA运行库下载尚未完成，服务未启动，**零样本大模型结果未产生**。后续真实结果更新本文件，不另建进度台账。

复现核验：下载入口补全七分类来源说明后，metadata摘要改变，七张CSV及许可文件均未改变。原metadata已按首次运行摘要恢复保存，v1输出保留；用当前metadata在`outputs/knowledge/ddinter-lists-partial-repro-v1/`独立复跑，逐条回答、检索证据及全部聚合指标完全一致。聚合JSON保留旧来源对象与两版摘要，避免把来源说明更新误当成数据变更。

## 5. 最小复现命令

以下在仓库根目录执行，已有输出拒绝覆盖；维护者电脑的本轮结果应直接读取，另跑使用新版本目录。

```powershell
.venv/Scripts/python.exe src/data_evaluation/fetch_open_ddi.py --dataset ddicorpus
.venv/Scripts/python.exe src/data_evaluation/fetch_open_ddi.py --dataset ddinter --seven-category-snapshot
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddicorpus prepare
.venv/Scripts/python.exe -m src.knowledge.train_text_baseline
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddi_lists prepare
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddi_lists prepare-permuted
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddi_lists first-two --prepared data/processed/knowledge/ddi-lists-20261114 --output outputs/knowledge/ddi-list-first-two-v1-repro
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddi_lists first-two --prepared data/processed/knowledge/ddi-lists-permuted-20261114 --output outputs/knowledge/ddi-list-first-two-v2
.venv/Scripts/python.exe -m src.knowledge.ddinter_baseline --allow-partial
.venv/Scripts/python.exe -m unittest discover -s src/knowledge/tests -v
```

本轮13项知识模块测试通过，覆盖未知/缺失分母、固定划分、输入位置变换、标签隔离、DDInter去重与未知等级。模型加载和零样本实际运行尚未通过，单元测试不能替代它们。

本地模型真正加载与非医疗冒烟通过后，先用development输入只检查格式。以下为**待执行**命令，不是本轮运行证据；如格式检查暴露问题，保留首次响应并记录改动，不能一边看pilot答案一边修提示词。

```powershell
$runtime = 'models/knowledge/qwen3-4b-instruct-2507-q4km/source.json'
$lists = 'data/processed/knowledge/ddi-lists-permuted-20261114'
$corpus = 'data/processed/knowledge/ddicorpus-pilot-v1'
.venv/Scripts/python.exe -m src.knowledge.run_local_pilot --task lists --inputs "$lists/development.inputs.jsonl" --output outputs/knowledge/ddi-list-local-dev-v1 --runtime $runtime
.venv/Scripts/python.exe -m src.knowledge.run_local_pilot --task corpus --inputs "$corpus/development-inputs.jsonl" --output outputs/knowledge/ddicorpus-local-dev-v1 --runtime $runtime
# 格式检查完成且提示词固定后，再运行下面两批pilot。
.venv/Scripts/python.exe -m src.knowledge.run_local_pilot --task lists --inputs "$lists/pilot.inputs.jsonl" --output outputs/knowledge/ddi-list-local-v2 --runtime $runtime
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddi_lists evaluate --prepared $lists --responses outputs/knowledge/ddi-list-local-v2/responses.jsonl --run-info outputs/knowledge/ddi-list-local-v2/run-info.json --output outputs/knowledge/ddi-list-local-v2/evaluation
.venv/Scripts/python.exe -m src.knowledge.run_local_pilot --task corpus --inputs "$corpus/pilot-inputs.jsonl" --output outputs/knowledge/ddicorpus-local-v1 --runtime $runtime
.venv/Scripts/python.exe -m src.knowledge.evaluate_ddicorpus evaluate --prepared $corpus --responses outputs/knowledge/ddicorpus-local-v1/responses.jsonl --method local_zero_shot --report outputs/knowledge/ddicorpus-local-v1/evaluation.json
```

清单评价必须显式指定同一个v2目录，不能套用原序标签。下载和启动步骤见LOCAL_INFERENCE.md，下载未齐不得把此阶段勾成完成。
