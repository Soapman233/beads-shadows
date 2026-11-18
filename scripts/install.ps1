[CmdletBinding()]
param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'
$pythonCommand = Get-Command $PythonPath -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python not found. Install Python 3.10+ or pass -PythonPath.' }
if (-not $npmCommand) { throw 'Node/npm not found. Install a supported Node.js version first.' }
& $pythonCommand.Source -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
$venvRoot = Join-Path $backendRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonCommand.Source -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $venvPython -m pip install -r (Join-Path $backendRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend installation failed.' }
Push-Location $frontendRoot
try {
    & $npmCommand.Source ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
finally { Pop-Location }
Write-Host 'Installation complete. No SAM model was downloaded.'
Write-Host 'Run: .\scripts\start.ps1 -Cpu'
