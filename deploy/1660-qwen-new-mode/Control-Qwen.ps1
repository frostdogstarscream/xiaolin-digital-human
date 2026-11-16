param([ValidateSet('Start','Stop','Status')][string]$Action='Status',[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman'
$stateDir=Join-Path $root 'avatar-2d\runtime\qwen-realtime-v2'
$statePath=Join-Path $stateDir 'process.json'
$runner=Join-Path $root 'deployment\qwen-new-mode-20261110\run_windows.py'
$python=Join-Path $root 'avatar-2d\.venv\Scripts\python.exe'
$mutex=New-Object Threading.Mutex($false,'Local\XiaolinQwenNewMode-Lifecycle')
$locked=$false
try {
    try {$locked=$mutex.WaitOne(120000)} catch [Threading.AbandonedMutexException] {$locked=$true}
    if(-not $locked){throw 'New-mode lifecycle is busy'}
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $saved=$null;$proc=$null
    if(Test-Path -LiteralPath $statePath){
        $saved=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $candidate=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
        if($candidate -and $candidate.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
            $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.Id)"
            if(-not $info.CommandLine.Contains($runner)){throw 'Owned process identity mismatch'}
            $proc=$candidate
        }
    }
    if($Action -eq 'Status'){
        if($proc){Invoke-RestMethod http://127.0.0.1:8771/api/health -TimeoutSec 5 | ConvertTo-Json -Depth 6}else{Write-Output 'New mode is stopped'}
        return
    }
    if($Action -eq 'Stop'){
        if($proc){
            [IO.File]::WriteAllText((Join-Path $stateDir 'stop.request'),'stop')
            if(-not $proc.WaitForExit(30000)){throw 'Graceful new-mode stop timed out; process retained for diagnosis'}
            $exitCode=$null
            $receipt=Join-Path $stateDir 'graceful-exit.json'
            if(Test-Path -LiteralPath $receipt){$exitCode=(Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json).exit_code}
            @{stopped=(Get-Date).ToString('o');pid=$proc.Id;exit_code=$exitCode} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateDir 'last-stop.json') -Encoding UTF8
        }
        # Stop only background services that this new-mode launch actually started.
        $oldModeActive=[bool](Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue)
        if(-not $oldModeActive){
            if($saved -and $saved.owns_mcp){& (Join-Path $root 'attendance-mcp\Stop-AttendanceMcp.ps1') -KeepRegistration}
            if($saved -and $saved.owns_fay){& (Join-Path $root 'fay-ue4\Stop-Fay.ps1')}
        }
        Write-Output 'New mode stopped';return
    }
    if(-not $proc){
        if(Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue){throw 'Old digital-human mode is active; stop it before starting the new GPU mode'}
        if(Get-NetTCPConnection -State Listen -LocalPort 8771 -ErrorAction SilentlyContinue){throw 'Port 8771 is occupied; no process replaced'}
        $ownsFay=-not [bool](Get-NetTCPConnection -State Listen -LocalPort 5010 -ErrorAction SilentlyContinue)
        $ownsMcp=-not [bool](Get-NetTCPConnection -State Listen -LocalPort 8783 -ErrorAction SilentlyContinue)
        & (Join-Path $root 'attendance-mcp\Start-AttendanceMcp.ps1')
        $logs=Join-Path $stateDir ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        New-Item -ItemType Directory -Path $logs -Force | Out-Null
        $proc=Start-Process -FilePath $python -ArgumentList @('-X','utf8','-u',('"'+$runner+'"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
        @{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');runner=$runner;logs=$logs;owns_fay=$ownsFay;owns_mcp=$ownsMcp} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        $deadline=(Get-Date).AddSeconds(120);$ready=$false
        do {
            if($proc.HasExited){throw "New mode exited; inspect $logs"}
            try {$health=Invoke-RestMethod http://127.0.0.1:8771/api/health -TimeoutSec 2;$ready=$health.status -eq 'ready'} catch {$ready=$false}
            if(-not $ready){Start-Sleep -Milliseconds 500}
        } until($ready -or (Get-Date) -ge $deadline)
        if(-not $ready){throw "New mode readiness timed out; inspect $logs"}
    }
    if(-not $NoBrowser){Start-Process 'http://127.0.0.1:8771/'}
    Write-Output 'New mode ready: http://127.0.0.1:8771/'
} finally {
    if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()
}
