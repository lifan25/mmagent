# 数据与代码准备状态

核查日期：2026-11-14。此处记录当前实际文件与检查结果，任务及后续结果由三位负责人更新各自 TASKS.md。

准备结论：A1 v3已就绪；当前推荐实验为38类、训练1433/验证354/测试351条，已完成20轮训练及重载，见[SSPNet报告](../src/recommendation/reports/sspnet-synthea-product-v4.md)。DDI来源、分母和第一批简单对照已实际核验，见[DDI诊断](../src/recommendation/reports/ddi-audit-20261114.md)。新下载MIMIC-IV Demo五表和250例DDI核查清单；真实大规模主队列仍未取得，用户愿意本人申请。本地病例、图和权重不随克隆取得，其他成员按说明重建。研究方向与零样本对照见[实验设计](research-design.md)。

用户最新要求暂不依赖申请中的队列：已完整取得DDICorpus-2013并实际跑完关系抽取轻量基线；七分类DDInter已做明确partial的检索实验；DialMed的dev/test及70药词表已到齐。数据与成绩各自对应任务，不能当作新增纵向临床验证。详细证据见[公开数据实验](../src/knowledge/reports/open-data-pilot-20261114.md)。

新成员按 [三人开工步骤](onboarding.md) 取得材料并做本机检查；不要把资源清单中组长电脑的已完成结果当作自己的验证记录。

当前路线：用户已同意采用相关公开数据和上游材料，不再等待作者提供完全相同的实验产物。保留 DXY 基线；推荐流程先用 MIMIC Demo 和 Synthea 合成病历开发，正式真实病例实验仍需足够规模的真实数据。更换数据属于适配实验，不能直接沿用原论文指标，也不单独构成研究贡献。

## 已取得并检查的数据

### 诊断数据

来源：[Diaformer 作者仓库](https://github.com/jymChen/Diaformer)，固定提交 45491f33145003290278d0eacdc87a1d1d786b2d。
文件：third_party/Diaformer/data/<数据集>_dataset/goal_set.p。

| 数据集 | 训练病例 | 测试病例 | 非空验证集 | 疾病数 | 文件中实际出现的症状数 |
|---|---:|---:|---|---:|---:|
| DXY | 423 | 104 | 无 | 5 | 41 |
| Muzhi | 568 | 142 | 无 | 4 | 66 |
| Synthetic | 24000 | 6000 | 无 | 90 | 266 |

已检查：文件可读取；train/test 非空；病例具有疾病标签和显式/隐含症状字典；当前症状值为布尔值；没有覆盖或重新划分原数据。

DXY、Muzhi 上述数量与 BIBM 表 I 一致，可以作为首轮目标；这不代表预处理、环境和模型训练已完成。先用 DXY 开始。

Synthetic：BIBM 表 I 报告 444 种症状，当前文件实际出现 266 种，现有词表也对应 266 种症状。采用手头版本时记录差异，不作为等待老师回复的前置条件。此诊断数据集与下文 Synthea 合成病历是两种不同的数据。

现有数据没有非空验证集。C 应核对作者的模型选择方法；需要增加验证集时从训练部分划分并记录偏差，不能以测试集反复选参。

复查命令：python scripts/check_diagnosis_data.py。

### MIMIC-III 公开 Demo

来源：[官方 Demo v1.4](https://physionet.org/content/mimiciii-demo/1.4/)。
位置：data/public/mimiciii-demo-1.4/。五张原始表、原许可证和来源说明已加入仓库。

| 表 | 数据行数 | 涉及患者数 |
|---|---:|---:|
| PATIENTS | 100 | 100 |
| ADMISSIONS | 129 | 100 |
| DIAGNOSES_ICD | 1761 | 100 |
| PROCEDURES_ICD | 506 | 88 |
| PRESCRIPTIONS | 10398 | 94 |

已检查字段、非空及患者范围一致性。CSV 列名为小写，上游旧程序可能使用大写。A1 已完成就诊关联、时间排序和候选筛选；药物分类映射仍由 B 实施。

Demo 支持数据流程开发，不足以复现论文指标。完整MIMIC-III权限未取得；当前正式真实主队列优先申请MIMIC-IV。

复查命令：python scripts/fetch_public_demo.py --check-only。

### Synthea 合成病历：推荐流程的替代开发数据

来源：[官方公开下载页](https://synthetichealth.github.io/downloads.html) 的历史 1K CSV 样本，[2020 年 4 月固定文件](https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_csv_apr2020.zip)。官方说明数据可用于研究等用途、不受真实患者隐私限制。原始压缩包缓存于 .cache；抽取的六张 CSV 在 data/local/synthea-apr2020/，保持本地，不自动提交病例。

实际检查：患者 1,171 人，就诊 53,346 行，诊断 8,376 行，操作 34,981 行，用药 42,989 行，过敏 597 行。下载页的“1K”是样本名称，不是精确统计。

- 1,257 次就诊同时记有诊断、操作、药物；其中至少两次的患者335人，这是 v2 严格操作条件。v3 允许空操作后，诊断/药物有效就诊3191次，至少两次的患者803人、候选2948次，已独立导出和划分。全量53346次仍全部保留。
- 本样本使用 SNOMED CT 诊断/操作及 RxNorm 药品编码；不能直接套用 MIMIC 的 ICD/NDC 处理。需按数据集单独建词表，并将药物映射到 DDI 支持的编号。
- 对 MoleRec 现有映射做 RXCUI 精确匹配：131 种原始 RxNorm 编码中 101 种有匹配，对应用药行 32,062/42,989。这个 131 是本样本的原始药品编码数，不等同于 SSPNet 论文的 131 种药物。尚未做成分归一化；未映射药物不能当作没有相互作用。
- 合成病历支持开发、接口验证和模拟实验，不能将其得分当作真实临床效果。慢性病的跨就诊延续等处理需单独定义，不默认补全。

下载/检查：python scripts/fetch_synthea_sample.py；只检查：python scripts/fetch_synthea_sample.py --check-only。

### 新增公开核查数据与真实队列路线

- **MIMIC-IV Demo 2.2**：官方五张CSV.gz已下载到 `data/local/mimic-iv-demo-2.2/`。100人、275次住院、4506条诊断、722条操作、18087条处方；保留原LICENSE与source.json。尚未完成该版本纵向有效样本筛选/映射，不能把原始住院数当预测数。
- **LLM-Uncertainty-DDI**：固定提交 `9872bb0c3e28cd03a7d460cdde3f01e0e8a26542`，已下载 `drug5.csv`、MIT许可及来源记录到 `data/local/llm-uncertainty-ddi/`。250份清单，C/D/X为81/92/77；每份均含目标交互，只用于核查定位/拒答评价，不是纵向病例或阴性清单误报验证。
- 下载/核验命令：`.venv/Scripts/python.exe src/data_evaluation/fetch_public_validation.py`。只读取公开固定文件，无额外依赖；以上数据均被Git忽略，不上传。路径、许可、本人申请步骤见[MIMIC访问说明](mimic-access.md)。
- **MIMIC-IV 3.1**：首选真实主队列，尚无权限。**AmsterdamUMCdb 1.0.2**作为跨来源外验候选，尚未申请/下载；需处理ICU入科与住院粒度、药物和诊断差异。[官方版本说明](https://amsterdammedicaldatascience.nl/)、[患者关联字段](https://github.com/AmsterdamUMC/AmsterdamUMCdb/wiki/admissions)。不能用同院MIMIC-III/IV自动宣称跨医院验证。
- **DDInter**：本地 `data/local/ddinter-public-20261114/` 已取得A/B/D/H/L/P/V七类、191820行、去重146518药对，缺R；来源在source.partial.json。已实际进行七分类检索实验，不能冒充完整库。[官方源](https://ddinter.scbdd.com/download/)与[CC BY-NC-SA 4.0条款](https://ddinter.scbdd.com/terms/)保留。未收录/Unknown不等于安全，CSV没有机制原文；若参与训练/调参，不把同一批边作独立真值。
- **DDICorpus-2013**：本地 `data/local/ddicorpus-2013/` 的作者ZIP、README许可及source.json完整；训练27792药对、正式关系测试5716药对。固定commit `819b0fa538ed83ab2a8b4f5417bba3c03249b7f3`、CC BY-NC 4.0。[作者仓库](https://github.com/isegura/DDICorpus)。文本关系任务与临床DDI安全判断分开，DrugNER占位false标签不进入关系实验。
- **DialMed**：本地 `data/local/dialmed/` 已有dev1192条、test1199条、70药标签、原MIT许可及附录，train未齐；固定commit `4cd19719ad8a25e0d2cb411cdede3aea9d9e095f`。[作者仓库](https://github.com/f-window/DialMed)。现有部分足以准备零样本，但对话推荐句仍含掩码结构，必须先冻结推荐前截断；本轮没有运行DialMed模型。

新增材料下载入口：`.venv/Scripts/python.exe src/data_evaluation/fetch_open_ddi.py --dataset ddicorpus`；七分类冻结参照加 `--dataset ddinter --seven-category-snapshot`；完整DialMed使用 `--dataset dialmed`。全部数据本地保留，不随Git上传。

### 直接查看病例

运行 python scripts/preview_cases.py，生成本地 outputs/data-preview/病例预览.md，以及 dxy.train.first10.json、mimic_demo.one_patient.json、synthea.one_patient.json。预览保持原字段，展示病例标签和已有处方，不是模型预测，也不是训练输入文件。全部忽略提交。

DXY 包含中文主诉、问诊及症状；MIMIC/Synthea 按多张 CSV 存储就诊、诊断、操作、药物。它们没有共同患者，不能拼接成一条真实病例。

## 已取得的代码

| 代码 | 位置与版本 | 当前能确认什么 |
|---|---|---|
| SSPNet | third_party/SSPNet；4a2695ec67e0dc30cd3fa8e67a4f1536f0bfc90d | 正常导入，src/recommendation 适配入口已完成20轮Synthea实际运行，空操作训练/测试通过 |
| Diaformer | third_party/Diaformer；45491f33145003290278d0eacdc87a1d1d786b2d | DXY 150 轮训练、验证选模、权重保存与重载、最终测试已完成：79/104，75.96%；见运行说明 |
| BIBM 完整实现 | 尚未取得 | 不能将 Diaformer 记作整篇 BIBM 的实现 |
| MoleRec 参考材料 | data/reference/MoleRec/（本地）；dd5afaf0a503fd3de3229f86ec7f26b345d10e3a | 已复制原预处理脚本、映射、分子辅助材料及原 README/LICENSE；不是 SSPNet 作者配套数据 |

原始来源：[SSPNet](https://github.com/ResearchGroupHdZhang/SSPNet)、[Diaformer](https://github.com/jymChen/Diaformer)。
BIBM DOI：10.1109/BIBM58861.2023.10385557，[作者主页提供的论文 PDF](https://hdzhangust.github.io/static/files/papers/2023%20BIBM%20Integrating%20Automated%20Knowledge%20Extraction.pdf)；SSPNet [正式论文](https://www.ijcai.org/proceedings/2025/1052.pdf)。

## 已找到的参考材料与剩余工作

### SSPNet

原 main.py 读取下面五种旧格式文件。当前运行改用本项目的 JSON/NPZ 适配产物，已实际准备，不以这些旧路径作为阻塞：

- records_final.pkl：病例序列。
- voc_final.pkl：诊断、操作和药物词表。
- ehr_adj_final.pkl：药物共现图。
- ddi_A_final.pkl：与词表对齐的药物相互作用图。
- ddi_mask_H.pkl：当前入口还会读取的辅助文件，需核对实际用途。

公开参考材料已经找到并保存到本地 data/reference/MoleRec/：processing.py、ndc2rxnorm_mapping.txt、ndc2atc_level4.csv、drug-atc.csv、atc2rxnorm.pkl、idx2SMILES.pkl、ddi_mask_H.py、ddi_mask_H.pkl、substructure_smiles.pkl。保留原 README、MIT LICENSE 与 source.json；来源是 [MoleRec](https://github.com/yangnianzu0515/MoleRec)，SSPNet README 也致谢该项目和 [SafeDrug](https://github.com/ycq091044/SafeDrug)。使用这些上游材料适配，不再等待相同文件由老师重发。

DDI原始文件已从SSPNet/MoleRec提供的[公开入口](https://drive.google.com/file/d/1s3sHmz9ueVA8YAGTARY8jwrhRdRvVaXs/view)保存为drug-DDI.csv：232,835,373字节、4,649,441行，关联来源为[TwoSIDES](https://tatonettilab.org/resources/tatonetti-stm.html)。按最低频40个事件组筛选得到476行；当前38类图75条无向边，EHR训练图172边，已独立重建核对。源关联不等于临床禁忌，CID映射不等于证据覆盖；与Decagon论文原始计数有差异，细节见DDI报告。旧24类34条DDI边/59条EHR边仅保留历史对照。

Synthea当前图与模型词表一致，仅从训练就诊建立EHR图，不混用上游预生成分子矩阵。适配入口修正四参数调用，ddi_mask_H为未使用的遗留参数，传None；显式初始化inter/garm，禁用绘图，以新循环解决原验证未定义变量和三次就诊跳过等问题。原子模块未改动。NDC/MIMIC模型适配和公共recommend接口仍待完成。

作者正文引用的附录尚未取得；正文学习率 1e-4 与当前入口默认 5e-4 不一致，采用设置必须记录。附录与作者精确配置作为可选补充，不阻塞公开材料上的适配开发。

### BIBM

尚未找到完整知识提取、规则迭代、MLN 学习与推理的公开整套实现和作者生成产物。论文已给出部分提示词模板与设置，不能称提示词全部缺失。[Alchemy](https://alchemy.cs.washington.edu/) 本体公开可得。C 可据原文自行实现最小流程并记录差异，不必先等作者完整代码；作者规则和缓存可后补对照。原诊断任务与用药核查扩展分开实施。

### 环境与资源

项目 .venv 已配置 Python 3.10.22、PyTorch 2.7.1+cu128 和锁定依赖。RTX 5060 Laptop GPU 约 8GB 显存，已通过实际矩阵计算与 DXY 冒烟训练；运行说明见 [DXY 基线](dxy-diaformer.md)。

Diaformer作者报告Python3.8/PyTorch1.8.0，当前使用现代环境记录差异。SSPNet已补齐PyG、torch-scatter、OGB、RDKit、scikit-learn等，58包兼容检查与正常包导入通过；20轮主运行使用更快的CPU逐样本计算。完整快照及安装脚本见 src/recommendation/environment-lock.txt 和 setup_environment.ps1。

用户尚无完整MIMIC-IV权限且愿意申请；本人身份、培训和协议尚待完成，当前先使用已有公开数据。零样本仅为补充，本地调用、输入过滤和评价入口已实现，但可选模型环境未完成，尚无大模型核查结果或付费调用。现有PyTorch GPU环境可用，主线不等待额外安装；详情见[本地环境](../src/knowledge/LOCAL_INFERENCE.md)。DXY本机GPU运行不表示BIBM整体已复现。

## 现在可以推进什么

- A：已有A1不重写；先对齐病例/推荐/核查协议与统一评价，接真实模块完成最小agent调用链；DialMed后移为补充。
- B：复核DDI诊断并交付类别编码边界，补公共recommend接口，固定候选给C；需要训练分母对照时只改一个因素。
- C：优先BIBM知识提取、规则与原诊断推理缺口，适配到用药核查并接B的候选；零样本pilot留作后续补充，后端不绑定Qwen。

当前优先级：两篇论文模块实现 → 统一接口和最小agent调用链 → 同条件模块消融 → 必要的零样本补充与独立确认。新数据与已完成探索保留复用，不以安装Qwen或额外CUDA为前置。不把包装、数据替换或“零样本”本身当作创新。

