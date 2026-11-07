$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "../..")
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "Install uv and add it to PATH before running this script."
}
if (-not (Test-Path -LiteralPath .venv/Scripts/python.exe)) {
    uv venv --python 3.10.22 .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create Python environment" }
}
& .venv/Scripts/python.exe -c "import sys; assert sys.version_info[:2] == (3,10)"
if ($LASTEXITCODE -ne 0) { throw "Use Python 3.10 for this recorded environment" }
uv pip install --python .venv/Scripts/python.exe torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed" }
uv pip install --python .venv/Scripts/python.exe -r src/recommendation/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
uv pip install --python .venv/Scripts/python.exe --no-deps --no-build torch-scatter==2.1.2+pt27cu128 --find-links https://data.pyg.org/whl/torch-2.7.0+cu128.html
if ($LASTEXITCODE -ne 0) { throw "Matching PyG scatter wheel installation failed" }
uv pip check --python .venv/Scripts/python.exe
if ($LASTEXITCODE -ne 0) { throw "Dependency compatibility check failed" }
