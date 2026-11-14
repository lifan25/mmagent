# 最小agent调用链

本入口使用已有结构化病例、SSPNet权重和已审核来源规则，依次执行输入检查、推荐、核查和下一动作整理。它是固定顺序的工具调用流程，没有新增大模型决策器，也不自动改处方。

## 本机前提

- 使用仓库已有`.venv`，SSPNet准备方式见[B运行说明](../recommendation/RUNNING.md)。
- 当前默认病例：`data/processed/data_evaluation/synthea-apr2020-v3/main_prediction_examples.jsonl`。
- 当前权重：`outputs/recommendation/sspnet-synthea-v3-product-cpu-seed8/best.pt`；词表与图在`data/processed/recommendation/synthea-v3-atc3-product-v4/`。这些文件不随Git克隆取得，缺失时需按B说明重建或在授权范围交接。
- 默认规则：`src/knowledge/rules/medication-llm-reviewed-v2.json`，真实模型生成后经agent来源/逻辑核对，2条启用、1条拒绝。来源核对参照为`medication-reference-v1.json`，3条；两者分别报告。
- 推荐与规则执行不需要本地语言模型服务。仅重新运行BIBM知识提取时，才按[本地CPU说明](../knowledge/LOCAL_INFERENCE.md)启动后端。

## 单个病例

在仓库根目录执行。`--index 0`固定取原文件第一条，不按输出挑病例；也可以把完整Case保存为JSON传入。

```powershell
.\.venv\Scripts\python.exe -m src.data_evaluation.pipeline --input data/processed/data_evaluation/synthea-apr2020-v3/main_prediction_examples.jsonl --index 0 --output outputs/data_evaluation/agent-case-auto-20261114.json
```

输出存在时拒绝覆盖，复跑换一个文件名。输入JSONL里的`target_medications`留在评价侧，只取`case`传给工具；Case内部出现当前用药答案字段则拒绝调用。

也可直接调用：

```python
from src.data_evaluation.pipeline import MedicationAgent

agent = MedicationAgent()  # 权重只加载一次
result = agent.run(case)
```

结果中的`recommendation`保留原候选；`check_report`记录已执行规则、来源、缺失字段和未覆盖范围；`trace`记录实际调用顺序。未支持输入时不会继续核查。`next_action`只提示补充信息或复核，不会编造患者事实。

| agent状态 | 含义 |
|---|---|
| needs_information | 输入或规则所需事实不足，候选如已生成则保留 |
| unsupported_input | 编码、历史或输入结构不受当前模型支持 |
| review_required | 至少一条有来源规则触发标记 |
| not_checked | 当前候选未获得适用的完整规则检查 |
| completed | 已覆盖规则检查完成；仍需看未覆盖范围，不表示临床安全 |
| error | 模型运行失败，不能显示候选为成功结果 |

## 固定队列集成核验

```powershell
.\.venv\Scripts\python.exe -m src.data_evaluation.evaluate --split test --output outputs/data_evaluation/agent-integration-auto-20261114
# 同样病例与候选，换成来源核对参照；不重训。
.\.venv\Scripts\python.exe -m src.data_evaluation.evaluate --split test --rules src/knowledge/rules/medication-reference-v1.json --output outputs/data_evaluation/agent-integration-reference-20261114
```

评价器只读取原A1患者划分，复用已存权重和0.5阈值，不训练、不选参。它一次调用取得推荐与全38类分数，再交核查。原351条全部计入输入分母；严格接口支持子集另报，与旧模型在同一子集上的分数逐项比较。不支持病例保留原因，不能以支持子集成绩冒充全队列成绩。

传`--rules <已审核规则包.json>`可在相同候选上比较来源参照与自动提取规则；逐例结果和分数写到本地，Git仅提交聚合报告。核查只加标记，不据此声称药物预测F1提高。实际数字见[本次集成报告](reports/agent-integration-20261114.md)。

当前ATC3输出不能确定具体成分、途径和制剂，不能用目标处方把这些字段补全。因此现有病例中可能全部缺少执行成分级规则的前提；规则触发和例外用明确虚构边界样例另外检查，不混入病例效果指标。DXY诊断单独运行，不接到不相干的Synthea患者上。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s src/data_evaluation/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s src/recommendation/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s src/knowledge/tests -v
```

共享协议仍为`0.1-draft`：接口已有实现，尚不冒充B/C成员均已确认并正式冻结。接口说明见[protocol.md](../../docs/protocol.md)。
