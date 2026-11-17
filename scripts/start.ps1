[CmdletBinding()]
param(
    [string]$PythonPath,
    [ValidateRange(1024,65535)][int]$Port = 8766,
    [switch]$Build,
    [switch]$Cpu,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'
if (-not $PythonPath) { $PythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe' }
$pythonCommand = Get-Command $PythonPath -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python not found. Run scripts/install.ps1 or pass -PythonPath with an existing environment.' }
$pythonExe = $pythonCommand.Source
& $pythonExe -c "import fastapi, uvicorn, multipart, PIL, numpy, cv2; import sys; print('Python ' + sys.version.split()[0] + ' / backend dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies missing. Use scripts/install.ps1 for first installation.' }
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($nodeCommand) { & $nodeCommand.Source --version }
else { Write-Warning 'Node is unavailable. An existing frontend build can still be served.' }
if ($Build -and -not $CheckOnly) {
    if (-not $npmCommand) { throw 'npm not found. Install Node.js to build the frontend.' }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) { throw 'Frontend dependencies missing. Run scripts/install.ps1 first.' }
    Push-Location $frontendRoot
    try { & $npmCommand.Source run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
    finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'dist\index.html'))) { throw 'Frontend build missing. Run scripts/start.ps1 -Build or scripts/install.ps1.' }
# A temporary bind checks the selected localhost port without touching an existing service.
$portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
$portProbe.ExclusiveAddressUse = $true
try { $portProbe.Start() }
catch { throw "Localhost port $Port is occupied. Choose another -Port; no existing process was stopped." }
finally { $portProbe.Stop() }
Write-Host "Preflight OK: http://127.0.0.1:$Port"
if ($CheckOnly) { Write-Host 'Check only: no server started; no dependencies downloaded.'; return }
$serverProcess = $null
$previousDisableSam = [Environment]::GetEnvironmentVariable('BEAD_DISABLE_SAM', 'Process')
$sessionLogs = Join-Path ([System.IO.Path]::GetTempPath()) ('beads-shadows-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sessionLogs | Out-Null
$stdoutPath = Join-Path $sessionLogs 'server.out.log'
$stderrPath = Join-Path $sessionLogs 'server.err.log'
try {
    if ($Cpu) { $env:BEAD_DISABLE_SAM = '1' }
    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'app:app', '--app-dir', ('"' + $backendRoot + '"'), '--host', '127.0.0.1', '--port', [string]$Port) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    [Environment]::SetEnvironmentVariable('BEAD_DISABLE_SAM', $previousDisableSam, 'Process')
    $serverHealth = $null
    $startupDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $startupDeadline) {
        if ($serverProcess.HasExited) { throw 'Server exited during startup.' }
        try { $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2; $serverHealth = [System.Text.Encoding]::UTF8.GetString($healthResponse.RawContentStream.ToArray()) | ConvertFrom-Json; break }
        catch { Start-Sleep -Milliseconds 400 }
    }
    if (-not $serverHealth) { throw 'Server did not become ready within 60 seconds.' }
    if ($serverProcess.HasExited) { throw 'Server exited before readiness was confirmed.' }
    Write-Host "Ready: http://127.0.0.1:$Port"
    Write-Host ("Mode: {0}; device: {1}" -f $serverHealth.mode, $serverHealth.device)
    Write-Host $serverHealth.detail
    Write-Host "Logs: $sessionLogs"
    Write-Host 'Press Ctrl+C to stop this server.'
    while (-not $serverProcess.HasExited) { Start-Sleep -Milliseconds 500 }
    if ($serverProcess.ExitCode -ne 0) { throw "Server stopped with exit code $($serverProcess.ExitCode)." }
}
catch {
    if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 15 | Write-Host }
    throw
}
finally {
    [Environment]::SetEnvironmentVariable('BEAD_DISABLE_SAM', $previousDisableSam, 'Process')
    if ($serverProcess -and -not $serverProcess.HasExited) { $serverProcess.Kill(); $serverProcess.WaitForExit() }
}


