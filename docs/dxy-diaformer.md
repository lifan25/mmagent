# DXY / Diaformer 基线运行说明

本页对应作者 Diaformer 的问诊与疾病预测基线。它不是 BIBM 的完整知识提取与 MLN 方法，也不是医疗 agent。

## 环境

| 项目 | 本次配置 |
|---|---|
| 系统 | Windows |
| Python | 3.10.22，项目独立 .venv |
| PyTorch | 2.7.1+cu128 |
| CUDA 运行库 | 12.8 |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，约 8GB 显存 |
| 运行精度 | float32，关闭 TF32，不使用混合精度 |
| 上游版本 | Diaformer 45491f33145003290278d0eacdc87a1d1d786b2d |

模型与优化器使用仓库固定的作者实现，不需要下载预训练大模型或调用付费 API。作者原环境为 Python 3.8 / PyTorch 1.8，本次为适配现有显卡使用上述环境，数值不保证与旧环境完全相同。

## 新成员配置环境

先安装 uv（如已安装可跳过），在项目根目录运行：

```powershell
python -m pip install uv
git submodule update --init --recursive
.\scripts\setup_diaformer.ps1 -Device cuda
```

setup 脚本需要 uv 命令可用；pip 提示 Scripts 目录未在 PATH 时，先按提示将该目录加入当前终端的 PATH。脚本把下载缓存和 Python 管理目录放在项目 .cache 下，避免 Windows 跨磁盘移动错误。

没有受支持 GPU 时可用 -Device cpu 配置 CPU 环境，并在运行时指定 --device cpu；本次未测 CPU 训练耗时。

直接依赖见 requirements/diaformer.txt，实际非 torch 依赖锁定在 requirements/diaformer-lock.txt；PyTorch 根据 CPU/cu128 平台单独安装。

## 数据与评价约定

- 原始 DXY 为 423 条训练、104 条测试，5 类疾病、41 种症状；原文件与词表保持不变。
- 在原训练集内，按疾病分层、固定 seed=8，约 20% 留作验证：339 条进入训练部分、84 条验证。
- 训练部分有 1 条没有任何症状，按作者预处理规则跳过，最终 338 条有效训练病例。
- 不使用原测试集选模型；固定设置后只对原始 104 条测试病例做最终评价。
- 150 轮训练，每 10 轮及最后一轮在验证集模拟问诊；按 0.8×诊断准确率 + 0.2×症状 F1 选择模型。此组合与作者代码的选模公式等价，但本次应用于验证集。
- 最终重新加载选定的权重，再评价测试集。症状命中指标沿用作者口径，包含数据中已记录的阳性和阴性症状，不仅是阳性症状。
- batch_size=16、lr=5e-5、warmup_steps=2000、max_turn=20、min_probability=0.012、end_probability=0.9。模型为 5 层、hidden_size=512、4 个注意力头，21,713,130 个参数。
- 训练保留作者 drop_last=True，每轮随机打乱后运行 21 个完整批次；验证与测试问诊不丢弃尾部病例。

## 运行命令

本机 .venv 已配置。训练前在项目根目录激活：

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
python scripts/run_dxy_baseline.py --smoke --device cuda --output outputs/dxy-smoke-new
```

smoke 只做两批训练及验证集问诊，不读取原测试集结果，不能作为性能报告。

完整运行：

```powershell
python -u scripts/run_dxy_baseline.py --epochs 150 --seed 8 --device cuda --output outputs/dxy-reproduce-seed8
```

当前终端不方便激活时，用 .venv/Scripts/python.exe 替代 python 即可。输出目录必须在 outputs 内且尚不存在；复跑时使用新目录，保留已有结果。

## 本次结果

2026-11-07 已完成 seed=8 的一次 150 轮运行。聚合结果见 [JSON](results/dxy-diaformer-seed8.json)。

| 指标 | 验证集选中的模型 | 原始测试集最终结果 |
|---|---:|---:|
| 病例数 | 84 | 104 |
| 诊断正确数 | 72 | 79 |
| 诊断准确率 | 85.71% | 75.96% |
| 症状召回率 | 81.34% | 75.41% |
| 症状精确率 | 12.17% | 12.41% |
| 症状 F1 | 21.17% | 21.31% |
| 平均询问次数 | 10.67 | 10.69 |

- 选中第 70 轮模型；共 3150 次参数更新、15 次验证集问诊评价，最终测试只评价选定模型一次。
- 训练损失从 4.0929 降到 0.4733；不以最后一轮损失决定测试模型。
- 程序记录的训练及验证/测试计时为 698.14 秒，约 11 分 38 秒，不含首次环境下载。
- PyTorch 峰值已分配张量显存为 662.53 MiB，不代表进程全部显存。
- 冒烟检查、四项协议测试、实际划分不重叠检查、最终正确数复算、权重重新加载均通过。

BIBM 表 II 中的 Diaformer/DXY 参考值为 83.9%。本次为独立验证集选模和现代环境下的单次运行，未达到该参考数值，不能称为原文数值已复现；不根据本次测试结果继续挑参数或轮次。

原始运行记录位于 outputs/dxy-diaformer-seed8；权重和病例级预测没有上传仓库。

## 与作者入口的差异

适配代码位于 src/knowledge/diaformer_baseline.py。上游子模块未修改。

1. 复用作者模型、优化器、批处理、两项训练损失、三个无序训练机制和交互问诊模拟。
2. 移除运行时源码中未使用的 DeviceObjType 内部导入，使现代 PyTorch 可以导入入口；本地预测 JSON 显式使用 UTF-8。
3. Windows 下 num_workers=0，避免子进程无法继承作者批处理所需全局状态。
4. 每轮恢复 model.train()，修正上游评价调用 model.eval() 后未在下一轮恢复训练模式的问题；这会影响 dropout 和数值。
5. 用训练集内验证替代上游对测试集的逐轮评价与保存选择；本次每 10 轮选模，不使用作者默认的每轮测试方式。
6. 按作者规则跳过空症状训练病例；验证与最终测试的交互评价保留全部病例。

因此，本结果用于证明基线已可训练和评价，不能称为逐项完全一致的原论文结果复现，也不能直接声称相对论文改善。

## 产物位置

实际运行目录 outputs/dxy-diaformer-seed8：

- config.json：环境、模型与参数。
- split_indices.json：本地训练/验证划分。
- history.jsonl：逐轮训练和验证汇总。
- best_model.pt：验证集选出的模型权重。
- validation-*.json、test-predictions.json：本地问诊预测。
- summary.json：最终聚合结果。

模型、划分和病例级预测留在本地，不进入 Git。仓库只发布适配代码、环境说明和不含病例内容的聚合结果。

## 接下来分工

- A：现在即可做 Demo 就诊关联、时间排序、评价约定及完整 MIMIC 申请。
- B：现在即可向老师补齐 SSPNet 预处理、药物映射、DDI 和附录；现有五个模型输入仍未生成。
- C：以本页基线验收为起点，取得老师的 BIBM 完整代码、提示词、规则与 MLN 设置，再接上完整诊断流程。调参只用训练/验证，不继续以测试集挑方案。
