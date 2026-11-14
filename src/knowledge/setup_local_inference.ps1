#Requires -Version 7.0
# Downloads one pinned, free model and a portable runtime; does not modify Python or PATH.
[CmdletBinding()]
param([ValidateSet('all', 'runtime', 'model')][string]$Component = 'all')

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$modelDir = Join-Path $repoRoot 'models/knowledge/qwen3-4b-instruct-2507-q4km'
$runtimeDir = Join-Path $repoRoot '.cache/llama.cpp-b12359-cuda13.5'
$downloadDir = Join-Path $repoRoot '.cache/knowledge-downloads'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force -Path $modelDir, $runtimeDir, $downloadDir | Out-Null

function Get-PinnedFile {
    param([string]$Url, [string]$Destination, [string]$Sha256)
    if (Test-Path -LiteralPath $Destination) {
        if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
            throw "Existing file does not match the pinned checksum: $Destination"
        }
        return
    }
    $partial = "$Destination.partial"
    $request = @{ Uri = $Url; OutFile = $partial; MaximumRetryCount = 3; RetryIntervalSec = 2 }
    if (Test-Path -LiteralPath $partial) { $request.Resume = $true }
    Invoke-WebRequest @request
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        throw "Downloaded file does not match the pinned checksum: $partial"
    }
    Move-Item -LiteralPath $partial -Destination $Destination
}

$modelRevision = 'a06e946bb6b655725eafa393f4a9745d460374c9'
$modelName = 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
$modelUrl = "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/$modelRevision/$modelName"
$modelSha = '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
$runtimeName = 'llama-b12359-bin-win-cuda-13.5-x64.zip'
$cudaName = 'cudart-llama-bin-win-cuda-13.5-x64.zip'
$releaseUrl = 'https://github.com/ggml-org/llama.cpp/releases/download/b12359'
$runtimeSha = '1de9ca1ff408d6e348ea0007c6880ad2393311a02e7799bcde26dc16daef03dd'
$cudaSha = 'c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba'

if ($Component -in @('all', 'runtime')) {
    Get-PinnedFile "$releaseUrl/$runtimeName" (Join-Path $downloadDir $runtimeName) $runtimeSha
    Get-PinnedFile "$releaseUrl/$cudaName" (Join-Path $downloadDir $cudaName) $cudaSha
    Expand-Archive -LiteralPath (Join-Path $downloadDir $runtimeName) -DestinationPath $runtimeDir -Force
    Expand-Archive -LiteralPath (Join-Path $downloadDir $cudaName) -DestinationPath $runtimeDir -Force
}
if ($Component -in @('all', 'model')) {
    Get-PinnedFile $modelUrl (Join-Path $modelDir $modelName) $modelSha
}

[ordered]@{
    manifest_kind = 'source_declaration_not_readiness'
    checked_component_this_invocation = $Component
    note = 'Source pins only. Component downloads are verified separately; this file does not prove model loading or inference.'
    base_model = 'Qwen/Qwen3-4B-Instruct-2507'
    quantization_repository = 'unsloth/Qwen3-4B-Instruct-2507-GGUF'
    quantization_revision = $modelRevision
    quantization = 'Q4_K_M'
    model_bytes = 2497281120
    model_sha256 = $modelSha
    model_url = $modelUrl
    license = 'Apache-2.0'
    license_url = 'https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/LICENSE'
    runtime_release = 'b12359'
    runtime_url = "$releaseUrl/$runtimeName"
    runtime_sha256 = $runtimeSha
    cuda_url = "$releaseUrl/$cudaName"
    cuda_sha256 = $cudaSha
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $modelDir 'source.json') -Encoding UTF8

Write-Output "Expected model path: $(Join-Path $modelDir $modelName)"
Write-Output "Portable runtime: $runtimeDir"
Write-Output "Verified requested component: $Component. source.json is a source declaration, not a readiness signal."
Write-Output 'No service was started. See src/knowledge/LOCAL_INFERENCE.md for the loopback-only command.'
