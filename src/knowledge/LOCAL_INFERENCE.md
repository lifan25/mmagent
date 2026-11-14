# 本地零样本推理环境

**定位更正：这是可选推理后端，不是两篇论文复现或agent集成的前置。零样本仅为补充；现有PyTorch 2.7.1+cu128的GPU调用已实测可用，无需重装系统CUDA或驱动。下述CUDA13.5包只为独立llama.cpp运行器服务。** 2026-11-14复查：D盘可用约77.12GiB、内存31.61GiB、RTX5060Laptop显存7.96GiB；磁盘能容纳约2.50GB权重及缓存，实际LLM加载能力尚未验证。现有文件与下载保留，不以其完成为主线门槛，也不自动追加环境或运行零样本。

**2026-11-14复查状态：模型分段下载仍运行，CUDA库仅有未完成文件，未观察到其原下载进程；服务未启动，真实模型冒烟与零样本实验均未运行。** 已下载的官方运行器通过SHA256和版本检查；这不等于模型已可用。下载不会自动启动服务或实验。本地 `outputs/knowledge/local-inference/preparation-status.json` 是上一阶段历史快照，不能把其中进程或状态当实时结果。

只准备一份开放权重量化模型和便携运行器；不改动项目 `.venv`、系统 PATH 或驱动。实际医学任务的提示词、样本、评价另行冻结。下文非医疗冒烟命令为待执行步骤，不是已取得结果。

## 固定资源

- 原模型：[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)，仅非思考模式，Apache-2.0。
- 量化：[Unsloth Q4_K_M](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/a06e946bb6b655725eafa393f4a9745d460374c9)，不是额外任务微调。文件2,497,281,120字节；完整修订号与SHA256写在准备脚本和本地 `source.json`。
- 运行器：[llama.cpp b12359](https://github.com/ggml-org/llama.cpp/releases/tag/b12359)，Windows CUDA13.5 x64。程序与CUDA库压缩包分别179,546,112和426,314,199字节；放在项目 `.cache`。
- 总下载约3.10GB，另需解压空间。模型及日志均已被Git忽略。

在仓库根目录用 **PowerShell 7** 执行：

```powershell
& ./src/knowledge/setup_local_inference.ps1
```

脚本校验官方发布摘要，支持 `.partial` 续传；不启动服务。可用 `-Component runtime` 或 `-Component model` 分开准备。本机已有PowerShell 7和可用CUDA设备，没有安装新Python依赖。`source.json`只声明来源与版本，**不是模型或整体环境就绪的标志**；即使仅完成runtime也可能存在这个文件，实际就绪需模型校验、加载和推理另行确认。

## 本次下载的续接

本次GGUF使用8段HTTP Range下载，已有52,175,341字节前缀。`.cache/knowledge-downloads/qwen-ranges.json`固定该前缀长度、官方URL、分段数、总长度和官方SHA256；`qwen-part-00.bin`到`qwen-part-07.bin`保留分段字节。

```powershell
# 只读进度，不启动下载；不把文件大小当成完整校验。
& ./.venv/Scripts/python.exe src/knowledge/download_model_ranges.py --status
```

快照记录了既有进程ID、创建时间、命令及会话。**先确认这些下载进程已结束，再执行续传命令；进程仍运行时不重复启动。** 后续进程ID可能被系统复用，不能直接照抄旧ID结束进程。当前临时下载进程执行`.cache/knowledge-downloads/finish_model_ranges.py`；若它退出而未完成，改用仓库中的受控入口复用同一批分段：

```powershell
& ./.venv/Scripts/python.exe src/knowledge/download_model_ranges.py
# 权重完成并校验后，更新明确标注为来源声明的metadata。
& ./src/knowledge/setup_local_inference.ps1 -Component model
# CUDA下载进程结束后，若runtime未完成则独立续传。
& ./src/knowledge/setup_local_inference.ps1 -Component runtime
```

分段入口仅处理这一份固定GGUF；检查服务器的精确Content-Range，每段有限重试，全部组装后验证完整文件SHA256。若中途在组装阶段被打断且前缀长度改变，它会拒绝覆盖，保留文件待核查。入口的`--status`已实测；完整下载和组装尚未完成，不能写成全流程验证通过。

不能同时运行两个模型下载入口；官方串行`setup -Component model`不复用分段文件，因此现有分段未完成时优先使用分段入口，避免重复下载。其他机器尚无分段时，可直接使用前节的官方串行准备脚本。所有分段及下载状态都被Git忽略，不随仓库克隆获得。

HF与ModelScope镜像的小块吞吐测试未显示加速优势，未采用其传输；当前实际权重仍来自上述固定官方HF URL。下载完成后也不会自动执行下文步骤。

## 启动与调用

**仅在下载校验完成后**运行以下命令，从仓库根目录启动，只监听本机。单并发、4096上下文；禁用context shift，实验调用方必须检查输入长度与完成原因。模型卡的最大上下文不等于本机配置。

```powershell
$repoRoot = (Get-Location).Path
$runtimeDir = Join-Path $repoRoot '.cache/llama.cpp-b12359-cuda13.5'
$modelPath = Join-Path $repoRoot 'models/knowledge/qwen3-4b-instruct-2507-q4km/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
$logDir = Join-Path $repoRoot 'outputs/knowledge/local-inference'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$serverArguments = @(
    '-m', ('"{0}"' -f $modelPath), '--host', '127.0.0.1', '--port', '18081',
    '--alias', 'qwen3-4b-instruct-2507-q4km', '--ctx-size', '4096',
    '--n-gpu-layers', '99', '--parallel', '1', '--batch-size', '256',
    '--ubatch-size', '128', '--jinja', '--no-webui', '--no-context-shift'
)
$serverProcess = Start-Process -FilePath (Join-Path $runtimeDir 'llama-server.exe') `
    -ArgumentList $serverArguments -WorkingDirectory $runtimeDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'server.stdout.log') `
    -RedirectStandardError (Join-Path $logDir 'server.stderr.log') -PassThru
$serverProcess.Id
```

等 `http://127.0.0.1:18081/health` 返回 `{"status":"ok"}` 后调用：

```powershell
$request = @{
    model = 'qwen3-4b-instruct-2507-q4km'
    messages = @(@{
        role = 'user'
        content = 'Fictional inventory: a blue crate contains 3 wooden cubes and a red crate contains 2 wooden cubes. Return only a JSON object with key total_cubes and its integer value.'
    })
    temperature = 0
    seed = 20261114
    max_tokens = 64
    stream = $false
    cache_prompt = $false
}
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:18081/v1/chat/completions' `
    -Method Post -ContentType 'application/json; charset=utf-8' `
    -Body ($request | ConvertTo-Json -Depth 5)
$response.choices[0].message.content
```

这是没有答案示范的虚构物品计数；`temperature=0`是本项目固定解码选择，不是模型卡推荐采样参数。不能据此假定同一seed跨硬件逐位相同。

使用结束后，在保留了本次进程对象的PowerShell中停止自己启动的服务：

```powershell
if (-not $serverProcess.HasExited) { $serverProcess | Stop-Process }
```

不要按进程名称批量结束其他服务，也不要将host改为公网地址。官方接口说明见[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/b12359/tools/server/README.md)。

## 设备兼容与实际验证

本机为RTX 5060 Laptop 8GB，驱动591.91报告CUDA13.1。[NVIDIA小版本兼容说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)允许CUDA13.x应用在满足最低驱动条件时运行，但功能/PTX仍可能受限；最终以本机加载和生成日志为准，不要求升级系统环境。

截至本轮交接，仅运行器版本检查完成：`1.0.0-dev (build 12359, commit b1b770d90)`。模型冒烟尚未运行，无推理延迟或医学任务结果；不会在本轮回复后自动启动推理。后续实际执行时再保存请求、响应、完成原因、耗时及GPU加载日志。
