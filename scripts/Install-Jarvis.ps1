param([switch]$Voice)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Resolve the Windows shim even when this terminal has a stale PATH.
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$npmExe = if ($npmCommand) { $npmCommand.Source } else { $null }
if (-not $npmExe) {
    $candidates = @(
        "$env:ProgramFiles\nodejs\npm.cmd"
        ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)') + '\nodejs\npm.cmd')
        "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd"
        "$env:LOCALAPPDATA\nodejs\npm.cmd"
    )
    $npmExe = $candidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}
if (-not $npmExe) {
    throw 'Node.js/npm was not found. Install it with: winget install --id OpenJS.NodeJS.LTS --exact --source winget'
}
$nodeExe = Join-Path (Split-Path -Parent $npmExe) 'node.exe'
if (-not (Test-Path -LiteralPath $nodeExe)) {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $nodeCommand) { throw 'npm was found but node.exe is missing. Repair the Node.js installation.' }
    $nodeExe = $nodeCommand.Source
}
# Child build commands also need node.exe.
$nodeDir = Split-Path -Parent $nodeExe
$env:Path = "$nodeDir;$env:Path"
& $nodeExe --version
if ($LASTEXITCODE -ne 0) { throw 'Node.js could not start.' }
& $npmExe --version
if ($LASTEXITCODE -ne 0) { throw 'npm could not start.' }

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Install Python 3.12 with the Windows launcher first.' }
    & $launcher.Source -3.12 --version
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 with the Windows launcher first.' }
    Write-Host 'Creating local Python environment...'
    & $launcher.Source -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}

$requirements = if ($Voice) { 'backend\requirements-voice.txt' } else { 'backend\requirements.txt' }
& $python -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

Push-Location (Join-Path $repoRoot 'frontend')
try {
    & $npmExe ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    & $npmExe run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}

& $python (Join-Path $repoRoot 'scripts\configure.py')
if ($LASTEXITCODE -ne 0) { throw 'Owner configuration failed.' }
Write-Host 'Installed. Start with powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Jarvis.ps1'
