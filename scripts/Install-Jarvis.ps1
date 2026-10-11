param([switch]$Voice)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host 'Creating local Python environment...'
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 with the Windows launcher first.' }
}
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$requirements = if ($Voice) { 'backend\requirements-voice.txt' } else { 'backend\requirements.txt' }
& $python -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Install Node.js LTS.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
& $python scripts\configure.py
if ($LASTEXITCODE -ne 0) { throw 'Owner configuration failed.' }
Write-Host 'Installed. Start with powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Jarvis.ps1'
