param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner=Join-Path $PSScriptRoot 'service\server.py'
$stateFile=Join-Path $PSScriptRoot 'runtime\process.json'
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
        Write-Output 'Evaluation already running: http://127.0.0.1:8768/'
        if($OpenBrowser){Start-Process 'http://127.0.0.1:8768/'}
        return
    }
}
$logs=Join-Path $PSScriptRoot ('runtime\launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$process=Start-Process -FilePath $python -ArgumentList @('-u',('"'+$runner+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
@{pid=$process.Id;runner=$runner;start_time_utc=$process.StartTime.ToUniversalTime().ToString('o');logs=$logs} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
$deadline=(Get-Date).AddSeconds(90)
do{
    if($process.HasExited){throw "Evaluation exited; inspect $logs"}
    try{$health=Invoke-RestMethod 'http://127.0.0.1:8768/api/health' -TimeoutSec 3;$ready=$health.state -eq 'ready';if($health.state -eq 'error'){throw 'Candidate failed to load.'}}catch{$ready=$false}
    if(-not $ready){Start-Sleep -Milliseconds 500}
}until($ready -or (Get-Date) -ge $deadline)
if(-not $ready){throw "Evaluation preparation timed out; inspect $logs"}
Write-Output 'Evaluation ready: http://127.0.0.1:8768/'
if($OpenBrowser){Start-Process 'http://127.0.0.1:8768/'}
