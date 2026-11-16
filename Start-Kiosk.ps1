param([switch]$ServicesOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
$logDir = Join-Path $runtimeDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$serviceExe = Join-Path $projectRoot 'Service\AvatarService.exe'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$nativeExe = Join-Path $projectRoot 'Windows\HoloKiosk.exe'
if (-not (Test-Path -LiteralPath $nativeExe)) { $nativeExe = Join-Path $projectRoot 'unity\Builds\Windows-Quaternius\HoloKiosk.exe' }
$owned = @{}

function Start-LocalService([string]$kind, [int]$port) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        $expected = if ($kind -eq 'demo') { 'avatar-demo' } else { 'avatar-kiosk' }
        if ($health.service -ne $expected) { throw "Port $port is in use by another service." }
        return $null
    } catch {
        if ($_.Exception.Message -like '*in use*') { throw }
    }
    if (Test-Path -LiteralPath $serviceExe) {
        $executable = $serviceExe
        $arguments = @('--port', "$port")
    } elseif (Test-Path -LiteralPath $pythonExe) {
        $executable = $pythonExe
        $arguments = @(('"' + (Join-Path $projectRoot 'tools\service_runner.py') + '"'), '--port', "$port")
    } else { throw 'Local service runtime missing. Use the packaged delivery or run tools\Setup.ps1 first.' }
    if ($kind -eq 'demo') { $arguments += '--demo' }
    $proc = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "$kind-out.log") -RedirectStandardError (Join-Path $logDir "$kind-error.log")
    return $proc
}

try {
    $owned['demo'] = Start-LocalService 'demo' 8766
    $owned['kiosk'] = Start-LocalService 'kiosk' 8765
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try { $status = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 1; if ($status.ok) { $ready = $true; break } } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Local service failed to start. See runtime\logs.' }
    if ($ServicesOnly) {
        Write-Output 'Local services are ready on ports 8765 and 8766. Close this window to stop owned services.'
        while ($true) { Start-Sleep -Seconds 5 }
    }
    if (-not (Test-Path -LiteralPath $nativeExe)) { throw 'Native player is not built yet. Run tools\Build-Windows.ps1.' }
    $player = Start-Process -FilePath $nativeExe -WorkingDirectory (Split-Path $nativeExe -Parent) -WindowStyle Normal -PassThru
    while (-not $player.HasExited) {
        Start-Sleep -Seconds 3
        foreach ($kind in @('demo', 'kiosk')) {
            if ($owned[$kind] -and $owned[$kind].HasExited) {
                $port = if ($kind -eq 'demo') { 8766 } else { 8765 }
                $owned[$kind] = Start-LocalService $kind $port
            }
        }
    }
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Avatar kiosk startup') | Out-Null
} finally {
    foreach ($proc in $owned.Values) {
        if ($proc -and -not $proc.HasExited) { $proc.Kill(); $proc.WaitForExit(3000) | Out-Null }
    }
}
