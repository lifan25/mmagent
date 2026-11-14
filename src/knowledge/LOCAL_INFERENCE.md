# 本地知识提取后端：CPU运行

本后端用于BIBM式离线知识形式化。SSPNet、已保存规则的核查及agent调度均不依赖此服务；零样本推荐实验后置。提取请求只含公开来源文本，不含病例。

2026-11-14实测：权重已完整下载并通过官方SHA256核验；已有llama.cpp运行器在CPU上加载成功。虚构物品计数返回正确JSON，9个输出token约0.98秒；这是运行检查，不是医学准确率或完整吞吐基准。本次未安装新CUDA、驱动或Python依赖；此前未完成的CUDA下载文件保留，不自动续传。

## 固定资源

- 原模型：[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)，Apache-2.0。
- Q4_K_M：[量化固定提交](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/a06e946bb6b655725eafa393f4a9745d460374c9)，2,497,281,120字节；SHA256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`。
- [llama.cpp b12359](https://github.com/ggml-org/llama.cpp/releases/tag/b12359)：已下载Windows包包含CPU后端，本轮使用`--device none --n-gpu-layers 0`。
- 本机检查时D盘剩余77.12GiB、内存31.61GiB、RTX5060Laptop显存7.96GiB；原PyTorch GPU调用可用。模型、缓存和日志不随Git克隆取得。

## 准备与启动

已有文件的电脑直接启动即可。新电脑确需此可选后端时，用PowerShell 7在仓库根执行：

```powershell
& ./src/knowledge/setup_local_inference.ps1 -Component cpu
```

默认cpu只准备模型及含CPU后端的运行器，不取CUDA配套库；model只准备模型。all/runtime会取额外CUDA库，当前主线不需要。source.json声明来源，实际可用性以加载和生成记录为准。

下面采用本次CPU参数。先确认18081没有已有服务；新建日志目录，单并发按批调用。

```powershell
$taskRoot = (Get-Location).Path
$taskRuntime = Join-Path $taskRoot '.cache/llama.cpp-b12359-cuda13.5'
$taskModel = Join-Path $taskRoot 'models/knowledge/qwen3-4b-instruct-2507-q4km/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
$taskLogs = Join-Path $taskRoot 'outputs/knowledge/bibm-local-inference-next'
if (Test-Path -LiteralPath $taskLogs) { throw '请选择新日志目录' }
New-Item -ItemType Directory -Path $taskLogs | Out-Null
$taskArgs = @('-m', ('"{0}"' -f $taskModel), '--host', '127.0.0.1', '--port', '18081',
  '--alias', 'qwen3-4b-instruct-2507-q4km', '--ctx-size', '4096',
  '--n-gpu-layers', '0', '--device', 'none', '--parallel', '1', '--threads', '6',
  '--jinja', '--no-webui', '--no-context-shift')
$taskProc = Start-Process -FilePath (Join-Path $taskRuntime 'llama-server.exe') `
  -ArgumentList $taskArgs -WorkingDirectory $taskRuntime -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $taskLogs 'server.stdout.log') `
  -RedirectStandardError (Join-Path $taskLogs 'server.stderr.log') -PassThru
$taskProc.Id
Invoke-RestMethod 'http://127.0.0.1:18081/health'
```

首次加载需要等待，health返回status=ok后才调用提取。接口为`http://127.0.0.1:18081/v1/chat/completions`。固定温度0、seed20261114，实际请求保存提示词、结构约束、响应、完成原因和耗时；格式失败保留，模型自评分不能代替来源审核。诊断说明见[BIBM_DIAGNOSIS.md](BIBM_DIAGNOSIS.md)，具体提取结果见各实验报告。

任务结束后，在持有本次进程对象的同一个PowerShell停止自己的服务：

```powershell
if (-not $taskProc.HasExited) { $taskProc | Stop-Process }
```

本次启动记录、CPU加载和生成证据位于`outputs/knowledge/bibm-local-inference-20261114/`。早先`outputs/knowledge/local-inference/preparation-status.json`是下载阶段的历史快照，不能当作当前进程或就绪状态。分段工具保留供未下载完整的机器续接；本机不需重复下载。
