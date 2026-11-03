param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
& (Join-Path $workspace 'avatar-2d\Start-LocalASR.ps1')
& (Join-Path $workspace 'fay-ue4\Start-Fay.ps1')
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner=Join-Path $PSScriptRoot 'service\server.py'
$runtime=Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$stateFile=Join-Path $runtime 'process.json'
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
        Write-Output 'LiteAvatar is already running: http://127.0.0.1:8767'
        if($OpenBrowser){Start-Process 'http://127.0.0.1:8767/'}
        return
    }
}
$logs=Join-Path $runtime ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-u',('"'+$runner+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
@{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');runner=$runner;logs=$logs} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
$deadline=(Get-Date).AddSeconds(90)
do{
    if($proc.HasExited){throw "LiteAvatar exited; inspect $logs"}
    try{$health=Invoke-RestMethod 'http://127.0.0.1:8767/api/health' -TimeoutSec 3;$ready=$health.model_state -eq 'ready';if($health.model_state -eq 'error'){throw 'LiteAvatar model failed to initialize.'}}catch{$ready=$false}
    if(-not $ready){Start-Sleep -Milliseconds 500}
}until($ready -or (Get-Date) -ge $deadline)
if(-not $ready){throw "LiteAvatar startup timed out; inspect $logs"}
Write-Output 'LiteAvatar ready: http://127.0.0.1:8767'
if($OpenBrowser){Start-Process 'http://127.0.0.1:8767/'}
