# SSPNet：Synthea v3 实际运行步骤

本入口正常导入固定版本的原 SSPNet 模型，不再使用 A1 空操作探针的类提取方式。上游源码不修改，适配位于本目录。它是公开合成数据上的运行验证，不是原论文 MIMIC 指标复现。

## 1. 环境

已实际使用 Windows、Python 3.10.22、torch 2.7.1+cu128。完整快照见 environment-lock.txt，模型直接依赖见 requirements.txt。环境沿用原 DXY .venv 并补齐依赖，未更换 PyTorch/NumPy；快照中也包含已有 DXY 包。

当前维护者电脑已配好，无需重复安装；训练命令直接使用 .venv/Scripts/python.exe。本机 uv 工具实际在 ../.cache/uv-runtime/bin/uv.exe，未加入 PATH 时可用该路径替换下面的 uv 命令；新机器先按下一段准备 uv。

新机器先安装 uv 并加入 PATH，在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File src/recommendation/setup_environment.ps1
```

脚本先安装官方 cu128 PyTorch，再安装固定版本 PyG、OGB、RDKit、scikit-learn、SciPy、pandas、matplotlib、dill，最后从官方匹配页安装 Windows/Python 3.10 的 torch-scatter 二进制包。PyTorch 2.7.* 对应 PyG 扩展页 torch-2.7.0+cu128，避免本机从源码编译。

依据：[PyG 安装说明](https://pytorch-geometric.readthedocs.io/en/latest/install/installation.html)、[匹配的扩展包列表](https://data.pyg.org/whl/torch-2.7.0+cu128.html)。包检查命令：

```powershell
uv pip check --python .venv/Scripts/python.exe
```

## 2. A1 源数据

先按 docs/onboarding.md 取得 Synthea CSV 和 MoleRec 映射/DDI，运行 A1 v3。A1 输出目录默认为 data/processed/data_evaluation/synthea-apr2020-v3/。

```powershell
.venv\Scripts\python.exe src/data_evaluation/prepare.py --dataset synthea
```

本目录不重新划分患者；所有候选、历史、目标均继承 A1 的固定集合。A1 或 B 输出目录已有文件时，请使用新版本配置目录重建，不覆盖旧数据。

## 3. 药物映射、词表和图

2026-11-07新增产品级映射配置，后续实验建议使用：

```powershell
.venv\Scripts\python.exe src/recommendation/prepare.py --config src/recommendation/configs/sspnet-synthea-product.json
.venv\Scripts\python.exe src/recommendation/train.py --config src/recommendation/configs/sspnet-synthea-product.json
```

新版固定NLM公开映射快照，加3项有成分/剂型依据的项目交叉表，得到38类、训练1433条、验证354条、测试351条。已完成20轮完整训练、验证选模、最佳权重保存重载与测试一次。测试Jaccard74.65%、F1 80.91%、AP89.44%，DDI率140/296=47.30%；实际耗时48.49分钟。完整结果与限制见[新版运行报告](reports/sspnet-synthea-product-v4.md)。详见[映射复核](reports/mapping-coverage.md)。输出目录为data/processed/recommendation/synthea-v3-atc3-product-v4，运行目录为outputs/recommendation/sspnet-synthea-v3-product-cpu-seed8，不覆盖旧版。旧24类权重不适用。

当前机器这些目录已存在，直接重复prepare/train会拒绝覆盖。查看已有运行请读取上述运行目录的results.json；若需另跑，先复制配置并修改prepared_dir（仅重建数据时）和run_dir，再用--config指定，不删除历史结果。上述两条命令适用于首次生成的新机器。

快照已随代码提交，可离线重建映射。fetch_mapping.py查询标准药物编号，保留API响应与版本；已有快照时拒绝覆盖。刷新时应改用新快照文件名和配置版本，不静默更新。

新版DDI率只在能连接源CID的药物对上计算，另报未映射对和映射比例，无法计算时为null。34/38类可连接CID，不能把剩余4类或图中无边解释为临床安全；与旧版DDI率的分母不同。该分母也进入训练时beta权重计算，并非仅改报告；具体影响须用固定其他设置的对照确认。2026-11-14溯源结果见[DDI诊断](reports/ddi-audit-20261114.md)。

**以下默认命令保留旧版24类完整运行的复现方式。**

```powershell
.venv\Scripts\python.exe src/recommendation/prepare.py
```

配置：configs/sspnet-synthea.json。只支持当前 Synthea RxNorm 输入。输出目录 data/processed/recommendation/synthea-v3-atc3-v1/ 包含 train/validation/test.jsonl、vocabulary.json、graphs.npz 和 manifest.json；不提交这些本地病例产物。

- RXCUI 精确匹配 ndc2atc_level4.csv 的 RXCUI 列，将 ATC5 列取前四字符，表示 ATC 第三级类别；不能把它误称为具体药物成分或第五级。层级依据见 [WHO 协作中心](https://atcddd.fhi.no/atc/structure_and_principles/)。
- 同一 RXCUI 对应多个第三级类别时不任取第一条，也不自动扩增标签，明确计为 ambiguous 并排除；无匹配计为 unmapped。
- 药物类别词表仅从训练就诊建立。验证/测试只评价可映射且在训练词表内的药物子集，空目标或无映射药物历史的样本另计排除。报告的是受限药物空间，不能解释为全部原始处方的准确率。
- 诊断/操作词表也仅来自训练数据。非空的未知编码映射到内部 UNK 并计数；空操作保持 []，不编码成假操作或 UNK。
- EHR 图仅统计训练就诊的药物共同出现，不使用验证/测试。DDI 图与同一药物词表对齐、对称、对角线为零。
- DDI 按上游 processing.py 字面选择频次最低的40个事件组，再按事件名称过滤；并列时按字典序固定。此处不是“最高频40种”或经核验的“最严重40种”。图含34条无向边，原始数据过滤后476行，不能把未连边当临床无相互作用。

## 4. 训练、验证选模、保存重载与最终评价

```powershell
.venv\Scripts\python.exe src/recommendation/train.py
```

默认 seed=8、隐藏维度64、Adam、lr=1e-4、20轮、阈值0.5、target_ddi=0.06、coef=2.5。当前小规模逐样本计算实测 CPU 更快，所以配置为 CPU；机器安装的 CUDA 包正常可用。选择设备依据吞吐，不依据测试分数。若改设备、轮数或映射，先复制配置，修改 run_dir，并用 --config 指定新文件。

target_ddi 是损失权重切换阈值，不保证测试DDI率必定低于该数值。旧24类测试6.41%；新38类CID映射范围内为47.30%，均如实报告，不根据测试结果反复修改超参数。

每轮遍历全部映射后训练样本；BCE、多标签 margin 与 DDI 动态加权沿用原训练公式。每步检查输出、损失和梯度有限性；不裁剪梯度（norm 上限为 infinity）。只用验证集逐就诊平均 Jaccard 选择 best.pt，固定阈值不在测试集调参；20轮后加载最佳权重到新模型，先用验证样例核对重载一致，再对整个固定测试集评价一次。

默认本地结果目录 outputs/recommendation/sspnet-synthea-v3-cpu-seed8/，含 history.jsonl、best.pt、test-scores.npy、test-predictions.jsonl、results.json。权重、逐病例预测和标识不提交 Git。results.json 有总体、当前空操作、历史空操作、两者均空的分组结果及实际训练步骤计数。

best.pt 保存 state_dict、配置、词表和最佳轮次，需要本适配模型和同版图加载；不能直接当作原 main.py 预期的裸 state_dict 文件。实际结果和聚合JSON见 [运行报告](reports/sspnet-synthea-v3.md)。

## 5. 与公开入口的适配差异

1. 使用原 SSPNetModel 的继承适配类，完整包和 GNN 依赖正常导入；没有另写替代网络。
2. 修正训练/评估调用：传入原 forward 实际要求的四个参数。ddi_mask_H 未参与该模型计算，传 None，不生成假的分子掩码。
3. 禁用原 visual 调试绘图，避免读取当前答案作图、写硬编码的用户目录和 TSNE 开销；当前输入的药物答案始终为空，目标只进入损失/评价。
4. 原 inter/garm 使用未初始化内存创建，适配入口显式初始化为0.1并保持可学习；不宣称这是作者原始初始化。
5. 不使用有未定义 drug_data 的原 Train 入口；新循环按原损失组织，保留 A1 的患者划分和实际样本掩码。
6. 取消原 eval 的患者少于三次即跳过逻辑，直接评价经过 A1 时间检查且有可用映射历史的样本，包括只有一次历史就诊的样本。
7. 本次只跑20轮完成运行验证，原 main 默认200轮；没有复现原文数据、药物数量或完整实验表格。
8. 主指标按就诊平均，另报告按患者先平均的结果；PRAUC 用各就诊全词表 average precision 的均值。旧24类DDI rate为全部预测药物对的总体比例；新38类只在CID映射对上计算，另报未映射对和映射比例。没有沿用原 Test 的重复抽取80%测试患者。

## 6. 检查

```powershell
.venv\Scripts\python.exe -m unittest discover -s src/recommendation/tests -v
```

检查覆盖歧义映射/无匹配、空操作与未知编码区别、图、手算指标，以及正常原包导入后的空操作实际训练、保存重载和当前答案独立性；新增DDI诊断和损失探针的手算边界检查。A1数据测试仍单独运行，不将单元检查与完整20轮运行混为同一类证据。

## 7. DDI诊断与第一批对照（不重训）

需先具备38类数据、MoleRec源文件与已完成的best.pt/test-scores.npy。首次在仓库根目录执行：

```powershell
.venv\Scripts\python.exe src/recommendation/audit_ddi.py
.venv\Scripts\python.exe -m src.recommendation.probe_ddi_loss
```

两者分别写入 `outputs/recommendation/ddi-audit-20261114/` 与 `outputs/recommendation/ddi-loss-probe-20261114/`。当前维护者电脑已完成，直接查看其中 results.json 即可；重复执行会保护已有输出。如确需复查，分别添加 `--output outputs/recommendation/ddi-audit-repeat` 或 `--output outputs/recommendation/ddi-loss-probe-repeat`，不要删除历史目录。第一条会流式扫描约465万条来源记录，并仅重新计算验证集分数；测试只读取已存分数。第二条只用32条固定训练样本，不执行优化器。

聚合JSON与结论在 [DDI报告](reports/ddi-audit-20261114.md)，包括图重建、两种DDI分母、历史/频次基线、分组结果和损失探针。既有测试已用于研究诊断，后续只作探索性结果；新方法正式确认需要未参与开发的数据。

## 8. 共享Case推理与交接（不重训）

`predict.py` 实现现有协议 `0.1-draft`，尚未代表三人正式冻结协议。默认读取38类运行的 `outputs/recommendation/sspnet-synthea-v3-product-cpu-seed8/best.pt`，并从其配置定位 `data/processed/recommendation/synthea-v3-atc3-product-v4/` 下的 vocabulary.json、graphs.npz、mapping-decisions.json 和 manifest.json。新机器需要同版权重和这些产物；仓库代码本身不包含它们。仅调用推理不需重建数据或重新训练。

在仓库根目录的Python程序中使用：

```python
from src.recommendation.predict import get_default_recommender, recommend

engine = get_default_recommender()  # 本进程只加载一次权重与辅助文件
scored = engine.score_case(case)   # 一次前向；A评价/集成优先用这个入口
recommendation = scored["recommendation"]
# scored还包含full_scores、medication_codes、threshold、encoded_input。
# 仅需公共Recommendation时，单独调用recommend(case)即可。
# 不要对同一病例再调用recommend(case)，否则会重复推理。
```

`full_scores` 是按 `medication_codes` 顺序排列的38个sigmoid分数，候选采用固定 `score >= 0.5`，没有重新选阈值或top-k。`encoded_input` 是 `[历史诊断/操作/药物整数集合, ..., 当前诊断/操作/空药物集合]`；这两个字段只供本地核验，不增加公共Recommendation字段。非ok输入的full_scores和encoded_input均为null；模型计算失败时encoded_input保留用于本地排错，full_scores为null。`engine.manifest` 可直接序列化成JSON，包含权重、词表、图、映射、源码的哈希，阈值、最佳轮次、设备、版本和原始A1来源。

接口的编码与返回约定：

- 诊断和操作按原始 `system|code` 精确匹配训练词表，当前数据system为 `SNOMED-CT`。未知编码不会自动送入内部UNK，也不会静默删掉。
- 历史用药接受原始 `RxNorm`，只使用固定mapping-decisions.json中的唯一ATC3映射且须在38类词表内；也接受词表内的 `ATC3`。歧义、未映射、词表外和错误system均返回 `unsupported_input`，整条病例不运行推理。
- 候选system固定 `ATC3`，四字符如 `N02B` 表示第三级药物类别。它不是具体成分或商品。给C查来源时不能借当前真实处方确定某个成分；类别到CID通常多对多，某一CID有证据不代表该类别所有药物都有证据。
- 当前和历史操作的 `[]` 保留为空集合，不补假操作；`null` 表示未取得信息，返回 `needs_information`。历史须按严格递增的非负整数visit_index排列，有诊断、至少一个已完成历史就诊，且至少一个历史就诊有可用药物；部分历史药物为空允许。history为null返回needs_information，history为[]或全部历史药物为空返回unsupported_input。
- 当前诊断为空返回needs_information。Case顶层额外的medications、target_medications或target被拒绝，当前模型药物输入始终为[]。context仍由A/C保存和使用，SSPNet不读取其中过敏、肾功能等事实；不要把候选分数解释成考虑了这些条件的临床安全概率。
- input_issues逐项包含code、field和message；非ok没有候选。execution=model_inference表示所选后端，不表示被拒输入实际运行过模型。产物缺失、词表顺序不一致、DDI图不匹配等初始化错误直接抛出，A应停止运行而不是回退成虚构候选。

默认CPU、PyTorch单线程，保持与旧运行相同条件。线程设置影响本进程；若嵌入其他应用，可显式 `SSPNetRecommender(num_threads=None)` 保留调用方设置。缓存只缓存模型对象，不按case_id缓存病例结果。固定产物的更改需重新创建实例/进程，不能热替换后继续沿用旧版本号。

首次核验与接口检查：

```powershell
.venv\Scripts\python.exe -m unittest src.recommendation.tests.test_predict -v
.venv\Scripts\python.exe -m src.recommendation.verify_predict
```

当前维护环境已完成上述核验。新增9项检查通过；351条旧编码测试分数与已存结果逐位一致；严格Case接口支持344/351，拒绝7条未知编码病例，支持部分有211条当前空操作。全部344条支持病例的编码一致，核验脚本另对1条调用公开score_case确认分数一致。A的全量集成评价另外负责逐病例调用共享接口，不将这个单病例检查说成已完成整链路评价。聚合证据见 [接口报告](reports/predict-interface-20261114.md)。

本地 `outputs/recommendation/predict-verification-20261114/` 含 results.json、model-manifest.json、encoded-test-scores.npy、case-encoding-alignment.jsonl 和 a1-case-handoff.json。最后一个文件给出同一条原始A1 Case、encoded_input、分数及独立evaluation_only_target_ids；答案不在Case内部。现有输出不覆盖，确需复查时加 `--output outputs/recommendation/predict-verification-repeat`。351条旧编码口径允许UNK，344条严格支持口径不同；A必须报告完整351分母和7条拒绝，再在同一支持子集比较原模型与知识核查结果。

## 9. 原始RxNorm药品标签v5

v5改为预测原始RxCUI，共72个训练药物标签：69个完整制剂、2个包装、1个成分规格；SCDC897718未给剂型，不补造。保持原A1患者划分与1433/355/351条病例。原38类配置、prepared和权重保留，默认 `get_default_recommender()` 仍加载旧版本。2026-11-14已完成唯一一次20轮CPU训练，实际37.17分钟，按完整355条验证病例选第16轮；完整351条测试Jaccard65.30%、F1 71.05%，AP82.21%仅341条可评价病例。完整方法和限制见 [v5报告](reports/sspnet-synthea-rxnorm-v5.md)与[聚合JSON](reports/sspnet-synthea-rxnorm-v5-results.json)。

公开药品元数据与CID桥已固定到本目录resources，不含病例。`fetch_rxnorm.py`仅查询标准药品编号的NLM historystatus，记录原响应、版本和来源；产品名称优先采用元数据，原始历史编号不自动改成现行替代品。`build_rxnorm_cid.py`将完整成分连接到固定参考CID；无法唯一关联的成分保留未知。DDI图仅包含完整映射产品对，部分阳性另行审计。首次克隆已包含这两个公开快照，取得A1和原DDI文件后直接准备及训练：

```powershell
.venv\Scripts\python.exe src/recommendation/prepare.py --config src/recommendation/configs/sspnet-synthea-rxnorm-v5.json
.venv\Scripts\python.exe -u src/recommendation/train.py --config src/recommendation/configs/sspnet-synthea-rxnorm-v5.json
```

本机快照、prepared与完整训练已完成，无需重下或覆盖。只有主动重建公开来源时才使用fetch_rxnorm/build_rxnorm_cid，并指定新的输出快照路径。桥脚本的`--offline`需要先前保存的67份官方成分响应缓存；新机器没有缓存时不能使用该选项，须联网取得元数据并记录版本差异。已有输出目录不能复用，复查另用新目录配置。

`data/processed/recommendation/synthea-v3-rxnorm-product-v5/`在原文件基础上增加drug-catalog.json。每条模型记录保留完整target_medication_codes、outside_train_target_codes、input_supported和outside_train_input_codes。未知输入的整数记录只为审计保留，evaluate不会运行它们。原始目标全未见的病例仍保留；Jaccard/F1中这些未见目标计漏报。AP只对真实推理且完整目标均在词表内的病例计算，单列样本/患者覆盖；没有可评价AP时返回null。

新版运行目录 `outputs/recommendation/sspnet-synthea-v3-rxnorm-cpu-seed8/` 沿用history.jsonl、best.pt、results.json等。test-scores.npy始终与351条prepared测试病例同序，7条输入拒绝的行是NaN，test-score-available.npy明确记录可用行；这些NaN表示没有预测，不能填零后算AP。test-predictions.jsonl为拒绝行写predicted=null，并保存input_supported和完整目标/OOV字段。验证选模按全部355条full-target Jaccard，拒绝病例计0，20轮与阈值0.5预先固定。

显式选择已训练的新版模型：

```python
from src.recommendation.predict import ROOT, SSPNetRecommender

engine = SSPNetRecommender(
    checkpoint_path=ROOT / "outputs/recommendation/sspnet-synthea-v3-rxnorm-cpu-seed8/best.pt")
scored = engine.score_case(case)
# scored结构不变；medication_codes是72个原RxCUI。
# recommendation候选为{"drug": {"system": "RxNorm", "code": ...}, "score": ...}。
# engine.drug_catalog含该训练词表的来源元数据，不能用当前目标处方补全候选。
```

需要比较旧38类与新72药品时，先由A固定相同病例、可支持子集和投影口径。药品级分数、ATC3投影分数以及DDI映射覆盖的分母分别报告；同CID的多个产品不等于独立化学对，没有DDI边也不能证明重复用药安全。

本机已完成351条公开score_case调用核验：344条支持病例编码一致，72维分数与保存值逐位相等；7条拒绝无前向、无伪造分数。证据在运行目录interface-verification.json，model-manifest.json记录模型版本`sspnet-case-v1-310ea9023b03cfcb`和权重/词表/图/源码指纹。run-source.json为运行中记录，训练后复核所列12个文件均未变化。第8节verify_predict.py是旧38类核验入口；新版整链路复核使用A统一评价入口及本节列出的独立检查点，不把旧入口当成新版验证命令。
