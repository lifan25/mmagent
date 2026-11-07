# SSPNet 空操作集合核验

日期：2026-11-07。结论：当前环境中的原模型计算类可处理空操作集合，因此 A1 v3 默认不再要求操作非空；完整训练仍需 B 配置和验收。

## 静态依据

SSPNet 的 proc_embedding、Encoder_SAB、PMA、decoder 都直接处理操作集合。上游 MoleRec 的 processing.py 通过 inner merge 将操作表连接到病例，因此预处理排除无操作记录，不足以证明网络必须有操作。SSPNet 的原模型没有显式禁止长度为零的操作张量。

## 实际运行

在项目根目录执行（需要已有 PyTorch 和 NumPy 环境）：

```powershell
.venv\Scripts\python.exe src/data_evaluation/probe_empty_procedures.py
```

PyTorch 2.7.1+cu128，CPU，seed=8，隐藏维度16，虚构词表5/4/6。检查以下五种输入：

| 场景 | eval 前向/反向 | train 模式前向/反向 | 改变当前药物答案是否影响预测 |
|---|---|---|---|
| 操作均非空 | 有限值，通过 | 有限值，通过 | 不影响 |
| 当前操作为空 | 有限值，通过 | 有限值，通过 | 不影响 |
| 历史操作为空 | 有限值，通过 | 有限值，通过 | 不影响 |
| 当前、历史操作均为空 | 有限值，通过 | 有限值，通过 | 不影响 |
| 单次就诊、操作为空 | 有限值，通过 | 有限值，通过 | 不影响 |

输出形状均为1×6，结果 JSON 保存在 outputs/data_evaluation/sspnet-empty-procedures.json，仅本地。

## 核验范围

完整包导入因缺少 torch_geometric 失败。脚本从原 MoleRec.py 提取未经改写的模型类体，加载实际 SetTransformer.py、layers.py，跳过无关导入；关闭 TSNE 绘图以避免外部路径写入和额外诊断依赖。原代码 inter/garm 由未初始化内存创建，测试将其固定为0.1。测试调用模型实际要求的四参数接口，而非现有错误的训练调用。

这验证了空集合计算路径在当前环境中可前向和求梯度，不代表完整包、正式训练、其他 PyTorch 版本或模型效果已经验收。上游源码未修改；没有填入虚构手术、UNKNOWN 操作或复制诊断来替代空集合。

## B 接入时需要做什么

保留空列表转为形状1×0的 LongTensor，不能在预处理/批处理时重新 inner join 丢失病例或随意填0。应沿用 source procedure_record_status=not_recorded 的语义：只表示源表没有操作记录，不是临床确认未做任何操作。

默认操作词表使用训练集中已记录的真实编码。若某次训练划分完全没有操作编码，需单独验证零大小词表或约定显式缺失表示，不能据本次非零词表测试假定已支持。B 仍需解决依赖、训练接口、绘图及参数初始化，并用实际模型配置复查空操作样例与三次就诊评估过滤。
