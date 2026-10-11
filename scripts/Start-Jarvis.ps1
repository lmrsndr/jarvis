$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run Install-Jarvis.ps1 first.' }
Set-Location $repoRoot
# Bind the inference server to the dedicated 16 GB card when starting it here.
$gpuLines = @(nvidia-smi --query-gpu=name,uuid --format=csv,noheader)
$gpu = $gpuLines | Where-Object { $_ -match 'RTX 5060 Ti' } | Select-Object -First 1
if (-not $gpu) { throw 'RTX 5060 Ti was not detected.' }
$env:CUDA_VISIBLE_DEVICES = ($gpu -split ',')[1].Trim()
$env:OLLAMA_VULKAN = 'false'
$env:OLLAMA_NO_CLOUD = 'true'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null }
catch {
    if (-not (Test-Path $ollamaExe)) { throw 'Install Ollama for Windows first.' }
    New-Item -ItemType Directory -Path 'storage\logs' -Force | Out-Null
    Start-Process $ollamaExe -ArgumentList 'serve' -RedirectStandardOutput 'storage\logs\ollama-out.log' -RedirectStandardError 'storage\logs\ollama-error.log'
}
Write-Host 'Jarvis: http://127.0.0.1:8000. Open in your TV browser and select TV mode.'
Write-Host 'If Ollama was already running, its existing GPU configuration is retained.'
& $python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
