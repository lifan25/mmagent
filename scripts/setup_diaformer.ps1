param(
    [ValidateSet("cuda", "cpu")]
    [string]$Device = "cuda"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot ".cache/python"
$env:UV_CACHE_DIR = Join-Path $projectRoot ".cache/uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "Install uv first: python -m pip install uv"
}
if (-not (Test-Path -LiteralPath ".venv/Scripts/python.exe")) {
    uv venv --python 3.10.22 .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
& .venv/Scripts/python.exe -c "import sys; assert sys.version_info[:2] == (3, 10), 'Use a separate Python 3.10 environment.'"
if ($LASTEXITCODE -ne 0) { throw "The existing .venv does not use Python 3.10." }
$torchIndex = if ($Device -eq "cuda") { "https://download.pytorch.org/whl/cu128" } else { "https://download.pytorch.org/whl/cpu" }
uv pip install --python .venv/Scripts/python.exe torch==2.7.1 --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { throw "Could not install PyTorch." }
uv pip install --python .venv/Scripts/python.exe -r requirements/diaformer-lock.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install the Diaformer dependencies." }
& .venv/Scripts/python.exe -c "import torch; print('torch:',torch.__version__,'cuda:',torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "The environment check failed." }
