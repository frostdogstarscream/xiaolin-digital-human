param([string]$Python = '',[switch]$OpenAdmin)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { $Python = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe' }
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Install the Python dependencies in a virtual environment first.' }
$logDir = Join-Path $PSScriptRoot ('runtime\launch-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$launched = @()
foreach ($entry in @(@('kiosk.demo:app',8781,'demo'),@('kiosk.app:app',8780,'adapter'))) {
    $port = [int]$entry[1]
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is occupied. Existing processes have been left untouched."
    }
}
try {
    foreach ($entry in @(@('kiosk.demo:app',8781,'demo'),@('kiosk.app:app',8780,'adapter'))) {
        $proc = Start-Process -FilePath $Python -WorkingDirectory $PSScriptRoot -ArgumentList @('-m','uvicorn',$entry[0],'--host','127.0.0.1','--port',[string]$entry[1]) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir ($entry[2]+'.out.log')) -RedirectStandardError (Join-Path $logDir ($entry[2]+'.err.log'))
        $launched += $proc
    }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        foreach ($proc in $launched) { if ($proc.HasExited) { throw "Service exited; see $logDir" } }
        $ready = $true
        foreach ($port in @(8780,8781)) {
            try { $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5; if (-not $response.ok) { $ready=$false } } catch { $ready=$false }
        }
    } until ($ready -or (Get-Date) -ge $deadline)
    if (-not $ready) { throw "Services did not become ready; see $logDir" }
    $launched | Select-Object Id,StartTime | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir 'processes.json') -Encoding utf8
    Write-Output 'Adapter and demonstration API ready. Fay and the packaged UE client must also be running for conversation.'
    if ($OpenAdmin) { Start-Process 'http://127.0.0.1:8780' }
} catch {
    foreach ($proc in $launched) { if (-not $proc.HasExited) { Stop-Process -InputObject $proc -ErrorAction SilentlyContinue } }
    throw
}
