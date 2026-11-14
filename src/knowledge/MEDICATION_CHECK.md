# 有来源的用药规则与核查

这是 BIBM 知识提取思路在用药核查上的适配。它接收 SSPNet 候选并标记问题，不改变候选集合；原 BIBM 的症状问诊、疾病规则和 MLN 诊断是另一条实现。当前 SSPNet 输出 ATC 第三级类别，不能据此认定具体成分。

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

后续真实候选核查的首要缺口是有依据的具体药物身份及规则必要事实。不能为了提高覆盖率，把源标签的成分禁忌扩大为整类禁忌，或从测试真实用药填入预测候选。
