# 有来源的用药规则与核查

这是 BIBM 知识提取思路在用药核查上的适配。它接收 SSPNet 候选并标记问题，不改变候选集合；原 BIBM 的症状问诊、疾病规则和 MLN 诊断是另一条实现。旧 SSPNet 输出 ATC 第三级类别，新版另支持72个原始RxNorm标签；粗类别不能据此认定具体成分。最新来源扩展见下方v2，旧阶段记录保留。

## 方法与边界

原论文 [§III.A–B，PDF 第3–5页](https://hdzhangust.github.io/static/files/papers/2023%20BIBM%20Integrating%20Automated%20Knowledge%20Extraction.pdf) 先取得权威来源、筛选与总结片段，再结合预定义谓词生成一阶逻辑，并按符号、谓词、逻辑关系、完整性评分和改写。论文的规则供 MLN 诊断使用。

本次最小链路是：核对官方药品标签 → agent 撰写忠实来源摘要 → 本地模型生成患者条件表达式 → 模型自评/最多一次改写 → 结构检查、有限虚构输入检查、再次核对来源 → 核查执行。差异明确如下：

- 网页寻找、来源摘要、谓词、ATC5 与剂型映射由 agent 预先提供，没有声称实现了自动网页检索/摘要。
- 本地 Qwen 只生成 `statement` 和 `condition`；来源、精确药物范围与编码来自已核对元数据。生成条件不是从参照 JSON 复制的。
- 使用 JSON 条件树和真/假/未知三值执行器，没有将本模块称为原论文 FOL→MLN 的逐项复现。
- 自评分 15 分仅决定是否改写，不能批准规则。生成物默认 `draft`，正式执行仅接受 `reviewed`。该标记仅表示 agent 核过来源与逻辑，不表示人类组员或医学专家审核。
- 三条来源是开发材料，有限真值表是程序核验，不是独立抽取准确率、临床正确率或泛化证据。来源摘要是转述，原文 URL 和章节完整保留。

## 接口

```python
from src.knowledge.check import check, load_rules

report = check(case, recommendation)  # 默认加载来源核对参照规则
# 显式指定另一份已审核规则包；传 [] 表示无规则，不回退默认包。
report = check(case, recommendation, load_rules("path/to/rules.json"))
# 实际本地模型生成、经来源核对的自动包：2条启用、1条拒绝。
report = check(case, recommendation, load_rules("src/knowledge/rules/medication-llm-reviewed-v2.json"))
```

遵守 `docs/protocol.md` 的 Case、Recommendation 与 CheckReport。`recommendation.status` 非 `ok`、病例关联或契约版本不一致时不执行。规则只产生 `flag`，不删除候选。`coverage.*_rule_count` 是候选—规则判断次数；另给候选数和实际已检查候选数，不能当作病人计数。

精确匹配药物要求 `drug={"system":"ATC5","code":"...","route":"oral","dose_form":"tablet"}`。缺途径/剂型则信息不足，已知范围不符则不检查；不从 ATC3 反推成分，也不读取当前真实处方补成分。

| 来源规则 | 适用成分和编码 | 必要患者事实 | 所保留边界 |
|---|---|---|---|
| [二甲双胍，2.3/4节](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=ca71c133-6c38-4b9e-80af-1949634157f4) | metformin，A10BA02 | `context.egfr_ml_min_1_73m2`，非负有限数值 | 严格低于30；30–45起始治疗建议不是同一禁忌 |
| [布洛芬，禁忌节](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=eeb8312f-7fd9-4c4f-8264-a7e63ff1aa9d) | ibuprofen，M01AE01 | `context.perioperative_cabg`，布尔值 | 当前CABG手术相关情境，不以遥远手术史代替 |
| [华法林，8.1及5.7节](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=72d3ea20-27e4-4368-a666-a9b76530dbb9) | warfarin，B01AA03 | `pregnant`、`mechanical_heart_valve`、`high_thromboembolism_risk`、`warfarin_benefit_outweighs_risk`，均在context中 | 妊娠禁忌保留完整例外；获益风险判断须外部已记录，不能由瓣膜/既往处方推断 |

三条规则只覆盖口服片剂所选标签范围。编码来源是 WHO ATC/DDD Index，每条 JSON 保留相应页面。父类 A10B/M01A/B01A 只用于说明“可能有关但尚缺具体身份”，不触发成分禁忌。

所有临床事实 `null` 或缺失都为未知；类型错误、非有限/负 eGFR 也为未知。eGFR的非负输入域已在提取前的谓词定义中规定，由固定执行器保障，不依赖模型是否在条件树里输出`minimum`。逻辑有明确短路语义：例如已知未妊娠，就无需要求机械瓣膜例外信息；反之妊娠且只知道有机械瓣膜，不能漏掉另外两项例外条件。

状态优先级：实际触发→`issues_found`；否则有必要事实缺失→`insufficient_information`；否则至少完整执行一项→`checked`；其余→`not_checked`。`checked` 仅说明所列规则范围内未触发，仍展示未知与未覆盖项，不能写成安全许可。

## 运行

从仓库根目录执行，使用现有 `.venv`，本模块无需新增依赖或 CUDA：

```powershell
.venv/Scripts/python.exe -m unittest src.knowledge.tests.test_medication_check -v
```

父任务启动的本地 CPU 服务地址为 `127.0.0.1:18081`。仅输入公开来源摘要、固定谓词和药物范围，不发送病例；单并发，与诊断提取协调使用。

```powershell
.venv/Scripts/python.exe -m src.knowledge.extract --prompt-version v2 --runtime models/knowledge/qwen3-4b-instruct-2507-q4km/source.json --output outputs/knowledge/bibm-medication-extraction-v2-20261114
```

已存在输出目录时拒绝覆盖；复跑必须另起版本。中断续跑可加`--resume`，仅复用完全相同配置和请求的已存响应，不重新采样已完成条目；已完成运行不能续跑。各运行保存实际请求/响应、结束原因、token 数、耗时、模型来源与提示词。`draft-rules.json` 不能直接变更状态冒充来源核对；审核需检查具体模型条件和自然语言、保留独立审核记录与原始文件定位。

## 2026-11-14 已有证据

- 专属单元测试13项通过，覆盖阈值、触发/不触发、未知、例外、不猜药物身份、超出剂型范围、草案禁用、候选不修改、契约错误及结构错误；另检查输出schema不包含临床答案、生成规则不能绕过固定输入域，以及实际自动包只执行已核对通过的两条规则。
- 来源核对参照文件：`rules/medication-reference-v1.json`，3条。它是 agent 编写的可核查参照，不是模型自动输出。
- 38类词表连接探针：`outputs/knowledge/medication-check-20261114/vocabulary-connectivity.json`。0/38能完成这三条成分规则；A10B、B01A、M01A 共3类缺具体身份，另35类未覆盖。该探针没有调用推荐模型，不计为真实预测覆盖指标。
- 模型提取v1：`outputs/knowledge/bibm-medication-extraction-20261114`，9次调用、269.33秒，5831输入token、1358输出token。3条最终均结构不合格，仍为draft。模型混淆患者条件与药物范围，华法林还丢失了例外的否定关系；自评分不能发现或修复这些错误。
- v2仅进行一次格式开发调整：明确statement是字符串、condition只含患者谓词，给一个非医学结构例子，并以JSON schema约束结构和允许的字段名；schema不提供医学阈值或完整条件树。保留v1失败，不向模型提供这三条参照条件，也不把开发改进称为泛化结果。
- v2实际结果：`outputs/knowledge/bibm-medication-extraction-v2-20261114`，8次调用，API累计179.47秒，5957输入token、1073输出token。第一条结束后出现Windows GBK打印字符错误；仅修控制台输出和精确复用已有响应后续跑，8条原始调用无重复采样。
- v2的三条结构均合法。布洛芬通过；二甲双胍保留正确的低于30阈值，但首次因缺少`minimum`在负数输入上产生一项程序检查差异。将既定eGFR输入域固定到执行器后，只对原始模型输出重算，模型临床条件和文本没有改动。原`results.json`保留，工程更正另记`post-domain-validation-audit.json`。
- 华法林的模型自然语言保留了完整例外，但最终条件树写成“妊娠且满足例外”时触发，缺少对例外的否定；81个虚构三值上下文中40个与参照不同。整条标为`rejected`，未用参照树替换，也未做第三轮提取。
- 最终自动包`rules/medication-llm-reviewed-v2.json`保留三条原始模型条件及文本；二甲双胍、布洛芬为`reviewed`，华法林为`rejected`。各条记录源义核对理由、原始调用行号和响应摘要、前置元数据及agent审核身份。前两条在6个、3个有限输入中与参照一致，不解释为总体准确率。

上述ATC3阶段的首要缺口是有依据的具体药物身份及规则必要事实；下方RxNorm集成解决了其中的最小连接问题。不能为了提高覆盖率，把源标签的成分禁忌扩大为整类禁忌，或从测试真实用药填入预测候选。

## RxNorm产品适配（2026-11-14，待审核）

新增独立包 `rules/medication-llm-rxnorm-scope-v1.json`，已接入A/B的RxNorm产品输出；旧自动包、来源参照和ATC3行为保留。模型原始 `statement`、`condition` 和审核状态逐项保持相同，只由agent适配身份范围并补充来源，未调用新语言模型、未新增临床条件。华法林错误条件继续 `rejected`。

```python
from src.knowledge.check import check, load_rules
rules = load_rules("src/knowledge/rules/medication-llm-rxnorm-scope-v1.json")
# recommendation.candidates[].drug 只需保持原产品编码，如 system=RxNorm, code=860975。
report = check(case, recommendation, rules)
```

`check` 按原RxCUI查独立冻结文件 `rules/rxnorm-rule-products-v1.json` 的 `products[code].identity`，不相信候选临时自报的身份，不把产品反推成ATC3再猜成分。该文件仅包含与三条既有规则有关的4个产品，并非完整药物词表。规则按单成分IN、口服途径、允许的精确剂型RxCUI匹配；复方没有在本次范围内扩展。

| 产品RxCUI | 原成分IN / 精确活性成分 | 官方剂型RxCUI | 保留的范围 |
|---|---|---|---|
| 198405、310965 | 5640 ibuprofen | 317541 Oral Tablet | 100mg/200mg口服片；release未特别声明 |
| 855332 | 11289 warfarin / 114194 warfarin sodium | 317541 Oral Tablet | 5mg口服片；规则仍拒绝 |
| 860975 | 6809 metformin / 235743 metformin hydrochloride | 316945 Extended Release Oral Tablet | 500mg、24HR缓释口服片；不得压成普通片 |

以上四产品在冻结时均为Active/SCD/单成分，RxTerms的途径原值均为 `Oral Pill`，规范化为 `oral`；普通 `Oral Tablet` 不额外编造“明确即释”属性。版本为 RxNorm `02-Nov-2026`、RxTerms `RxTerms202611`。成分/剂型依据 [NLM getRxcuiHistoryStatus](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRxcuiHistoryStatus.html)，途径依据 [NLM RxTerms](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxTerms.getAllRxTermInfo.html)；每个公开条目保留具体请求URL和原响应摘要，原JSON在本地 `outputs/knowledge/rxnorm-feasibility-20261114/`，没有发送病例。

二甲双胍新增ER范围有直接证据：[DailyMed缓释标签](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=17050df5-9e95-4e1b-ac75-34add289b139)（2026-07-07更新）的RxNorm表明确列860975，2.4/4节支持同一低于30的禁忌；不把30–45起始治疗限制改为同一禁忌。新增范围允许317541和316945，源文证据随触发结果输出。此为agent核对后的范围版本，不是新的LLM抽取成果或人类专家审核。

未知产品没有冻结元数据时返回 `not_checked`，明确 `product_metadata_missing` 与缺失身份，不造“无风险”；已确定适用成分而缺eGFR/CABG时仍为 `insufficient_information`。元数据中剂型/途径缺失也不执行。已有21项药物检查通过（原13项、新增8项），新增覆盖4产品分型、ER不能匹配普通片限定范围、缺元数据、缺事实、eGFR阈值、旧ATC3行为和拒绝规则保持不变：

```powershell
.venv/Scripts/python.exe -m unittest src.knowledge.tests.test_medication_check src.knowledge.tests.test_rxnorm_check -v
```

上下文已由A从原表提取，截止时点为同次就诊结束。eGFR采用同次就诊区间内最新有效值，同一最新时点有冲突则未知；CABG仅采用同次区间内已记录的阳性事实，缺记录不填阴性，远期CABG史不等于本次手术场景。这是回顾性核查，不能称入院时建议。

### 固定候选集成验收

本轮351条测试输入中，344条获得推荐，7条因不支持的编码明确拒绝。对同一RxNorm模型的固定候选，仅改变是否提供上述上下文；两次候选及完整分数向量完全一致。以下病例状态的分母为344条支持病例：

| 核查结果 | 不新增上下文 | 加入原表同次上下文 |
|---|---:|---:|
| `not_checked` | 247 | 247 |
| `insufficient_information` | 97 | 95 |
| `checked` | 0 | 2 |
| 执行的规则实例 | 0 | 2 |
| 触发警告的规则实例 | 0 | 0 |

351条测试输入中，14条有可用eGFR、3条有同次CABG阳性记录；与实际预测产品及启用规则匹配后，只执行了2次 `medication.metformin.egfr`，均未触发。**2/344=0.58%仅表示至少执行一条现有规则的支持病例比例，不是整张处方的核查覆盖率或安全验证。** 剩余规则和药物范围、缺失事实仍须保留为未知；0次警告不能解释为模型推荐安全。

廉价对照将旧ATC3模型的每个预测类别替换为该类在训练就诊中最常见的原RxCUI，在相同上下文中执行4次规则、产生1次警告。这是独立的产品预测基线，不是从粗类恢复真实成分；与新模型候选不同，现有计数不构成新模型核查效果更好的证据，也没有独立临床审核标签可判断警告准确率。

最终集成验证为90项单元测试通过，其中C模块39项；上面的21项是药物核查子集。C本次适配与集成未增加LLM调用；已有规则日常执行不需要启动Qwen。最小调用链已完成，仍待A审核，不能标为原BIBM完整复现。详细配置、上下文审计、推荐对照与结果见 [A的RxNorm集成报告](../data_evaluation/reports/rxnorm-agent-20261114.md)及[聚合JSON](../data_evaluation/reports/rxnorm-agent-20261114.json)。

## 来源与事实扩展v2（2026-11-14）

先检查训练/验证源字段和官方药品标签，冻结少量可表达规则，再对固定推荐执行核查。没有根据测试预测选择新阈值或药物。新增条件由agent直接形式化来源，**没有新模型或LLM调用，不能当作BIBM自动提取性能提升**。设计、来源参照与实际四分支结果由A统一报告：[核查覆盖实验](../data_evaluation/reports/check-coverage-20261114.md)。

新包 `rules/medication-source-reviewed-v2.json` 显式配 `rules/rxnorm-rule-products-v2.json`；原默认规则、v1产品及历史结果保持不变。v2有4个启用单药患者条件规则、1个候选对复核规则；旧华法林模型条件仍拒绝，不改成手写答案。15个冻结产品的完整成分、盐和剂型来自已提交NLM快照；口服途径由明确的Oral Product剂型组及口服片剂支持，复方不压成单一成分。

| 规则与产品 | 官方依据 | 所需事实和分类 |
|---|---|---|
| metformin ER 500mg，860975 | 既有[ER标签](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=17050df5-9e95-4e1b-ac75-34add289b139)，2.4/4 | eGFR严格低于30，`contraindication`；CrCl不是eGFR |
| ibuprofen 200mg，310965 | [200mg标签](https://www.dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=09972806-e064-238d-e063-6394a90a7434)，Do Not Use及RxNorm表 | 明确本次围CABG情境，`contraindication`；远期手术史不等于本次 |
| naproxen 500mg／naproxen sodium 220mg，198014／849574 | [500mg标签](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=d564f52d-171c-4e7d-974c-3a0e192e6c12)，4/5.1及RxNorm表；[220mg标签](https://dailymed.nlm.nih.gov/dailymed/fda/fdaDrugXsl.cfm?setid=7a87a339-4482-ec9e-3c77-7ccb9cea2c4c)，Do Not Use | 同一CABG事实，`contraindication`；两个规格分别有证据 |
| methylphenidate 20mg，1091392 | [口服片标签](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=c614cf55-b462-4f7e-b19c-6d22a47e509f)，5.2及RxNorm表 | 明确冠心病阳性时`avoid_use_warning`；不是新宣布的绝对禁忌 |
| 含oxycodone/hydrocodone/meperidine的6产品＋diazepam/clonazepam的2产品 | [FDA类别警告](https://www.fda.gov/drugs/information-drug-class/new-safety-measures-announced-opioid-analgesics-prescription-opioid-cough-products-and)、[成分列表](https://www.fda.gov/media/96472/download)、[diazepam 5mg](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=cd02d7f0-0fbe-4829-9a05-99a261972805)及[clonazepam 0.25mg](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=fa50aceb-a113-4c07-98e0-f1824d4ff30e)的boxed warning | 仅本次候选两类同时出现时`potential_combination_review`；确认是否拟并用，复核替代方案、剂量、时长和监测；**不是实际并用、已发生DDI或自动停药结论** |

独立来源复核发现旧ibuprofen处方标签列300/400/600/800mg，不能冒充100/200mg精确产品证据。新包补200mg直接标签；**100mg普通片198405虽身份明确，临床范围暂不覆盖**，不用100mg/5mL混悬液或咀嚼片冒充。旧v1结果保留并注明范围不足。naproxen500mg最终采用明确列198014的页面，不依赖仅375mg包装的页面。这些是证据核对后的范围修正，不是按覆盖结果调条件。

`coronary_artery_disease`表示截止前已可取得、未记录缓解的明确冠心病来源记录，不是新的临床诊断确认。来源就诊必须已结束，缓解日当天时分不明则未知；没有诊断不填false，不从药物、血压、症状或家族史推断CAD。A保存原始出处和时间。

未加入的候选：将CrCl偷换为eGFR；没有正常上限或病情判断的肝功能规则；一般哮喘当NSAID过敏；由性别/年龄猜妊娠；单孕激素norethindrone套用雌激素复方的吸烟禁忌；仅因年龄普遍可得就增加泛泛规则。现有过敏表也没有药物过敏或明确无过敏证据。能提取一个字段不等于它足以执行医学判断。

### 调用与计数

```python
from src.knowledge.check import check, load_rules, load_product_metadata
rules = load_rules("src/knowledge/rules/medication-source-reviewed-v2.json")
products = load_product_metadata("src/knowledge/rules/rxnorm-rule-products-v2.json")
report = check(case, recommendation, rules, product_metadata=products)
```

不传新产品表时默认仍用v1，不会静默替换旧结果。该v2文件中的产品审计版本现为`rxnorm-rule-products-v2.1`：补充77个已经有NLM源记录的原码清单。对于已知原码但明确不在任何规则允许产品清单内，记录`outside_reviewed_product_scope`，不再误报为缺患者事实或可补的身份；任意未知原码或范围内缺身份仍为未知。该清单不宣称77个药品的制剂或身份都完整解析，也不扩充临床范围。首次运行的过度pending计数保留，A用新输出目录复核修正，临床条件、允许范围和参考标签不变。

`coverage.checked_rule_count/pending_rule_count/checked_candidate_count`只统计单药—患者条件。`pair_coverage`另列`candidate_pair_count`（候选无序对总数）、`checked_pair_count`（匹配的组合复核）、`pending_pair_count`（可能匹配但身份或范围不明确）、`uncovered_pair_count`（不在该组合规则内）。本版本仅1个组合规则，不匹配不等于安全，药对不计入单药计数或称为患者数。

组合结果仍在`findings`，使用`candidate_indices`、`evaluation_unit=candidate_pair`、`classification=potential_combination_review`及`actual_concurrent_use=unknown`。不读取当前监督处方或历史药物猜并用；只有一个opioid候选时不会因历史有benzodiazepine产生组合警告。成分不完整或伙伴未知不产生阳性。

```powershell
.venv/Scripts/python.exe -m unittest src.knowledge.tests.test_source_rules_v2 -v
.venv/Scripts/python.exe -m unittest discover -s src/knowledge/tests -v
```

C50项单元测试通过（原39＋新增11），覆盖旧默认、范围收窄、CAD警告、复方完整性、候选不修改、组合顺序、未知伙伴和两种分母。最后一项专门区分已知范围外与真正未知；不是增加医学规则或提高覆盖的补丁。独立来源参照由另一角色在读新实现与生产输出前写固定标签；它是来源语义与实现一致性检查，与开发单元测试、真实病例覆盖和临床专家金标准分别报告。实际评分及集成结果见A报告。

### v2最终验收结果

固定候选四分支已完成，新旧病例与分数保持原样，旧基线逐例完整重现。最终本地产物为`outputs/data_evaluation/check-coverage-v2-20261114/results.json`；原351条输入中344条推荐支持、7条拒绝。新包和新事实下，344条的状态为244条`not_checked`、98条`insufficient_information`、2条`checked`，无警告。

**至少完成一个患者条件规则的病例仍为2/344（0.58%），没有提高覆盖。** 两次仍是metformin eGFR规则。单药—候选规则待补事实共116次：ibuprofen围CABG 55次、naproxen围CABG 34次、metformin eGFR 27次；次数不是患者数。新增CAD事实没有产生实际核查，因为本批预测中methylphenidate候选为0。29次metformin候选中只有2次具有可用eGFR，不能以其他诊断或旧测量填造当前值。

本批387个候选药对全部在这一组合规则范围外，`pending_pair_count=0`、`checked_pair_count=0`。opioid产品出现4次（1860154一次、833036三次），diazepam出现1次，但未在同一候选清单相交；不由此宣称不存在其他DDI或实际用药安全。首次运行的223个pair pending来自把已有源记录但明确范围外的原码误当身份未知；证据保留在`outputs/data_evaluation/check-coverage-20261114/`，更正仅改变范围与未知的记账，未改临床条件、允许范围、参考期望、实际执行或警告数。

由另一agent角色预先冻结的40条来源参照全部一致，未知误清、漏标、误标均为0；这证明该有限来源语义范围的实现一致性，**不是临床正确率或独立专家金标准**。本轮相关单元检查为A32＋C50共82项；B模型与源码未改，不重复B测试或训练。覆盖无提升这一结果保留，不为增加数字继续添加医学条件。完整四分支、分母和后续缺口见[A报告](../data_evaluation/reports/check-coverage-20261114.md)及[聚合JSON](../data_evaluation/reports/check-coverage-20261114.json)。
