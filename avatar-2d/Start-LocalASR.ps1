$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv-asr\Scripts\python.exe'
$runner=Join-Path $PSScriptRoot 'service\local_asr_server.py'
$runtime=Join-Path $PSScriptRoot 'runtime\asr-service'
$stateFile=Join-Path $runtime 'process.json'
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
        Write-Output 'Local FunASR already running: http://127.0.0.1:8780'
        return
    }
}
$logs=Join-Path $runtime ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-u',('"'+$runner+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
@{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');runner=$runner;logs=$logs} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
$deadline=(Get-Date).AddSeconds(60)
do{
    if($proc.HasExited){throw "FunASR exited; inspect $logs"}
    try{$health=Invoke-RestMethod 'http://127.0.0.1:8780/health' -TimeoutSec 2}catch{$health=$null}
    if($health -and $health.state -eq 'error'){throw "FunASR model failed; inspect $logs"}
    if(-not $health -or $health.state -ne 'ready'){Start-Sleep -Milliseconds 500}
}until(($health -and $health.state -eq 'ready') -or (Get-Date) -ge $deadline)
if(-not $health -or $health.state -ne 'ready'){throw "FunASR startup timed out; inspect $logs"}
Write-Output 'Local FunASR ready: http://127.0.0.1:8780'
