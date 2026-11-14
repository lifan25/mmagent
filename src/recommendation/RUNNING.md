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
