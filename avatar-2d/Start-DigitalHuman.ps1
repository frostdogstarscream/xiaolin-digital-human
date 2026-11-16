param([switch]$OpenBrowser,[switch]$Legacy)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner=Join-Path $PSScriptRoot $(if($Legacy){'service\app.py'}else{'service\live_app.py'})
$runtime=Join-Path $PSScriptRoot 'runtime\presenter-service'
$stateFile=Join-Path $runtime 'process.json'
if(-not $Legacy){& (Join-Path $PSScriptRoot 'Start-LocalASR.ps1')}
& (Join-Path (Split-Path -Parent $PSScriptRoot) 'fay-ue4\Start-Fay.ps1')
$attendanceRegistration=Join-Path (Split-Path -Parent $PSScriptRoot) 'attendance-mcp\runtime\registration.json'
if(Test-Path -LiteralPath $attendanceRegistration){
    $attendanceSettings=Get-Content -LiteralPath $attendanceRegistration -Raw -Encoding UTF8 | ConvertFrom-Json
    if($attendanceSettings.enabled){& (Join-Path (Split-Path -Parent $PSScriptRoot) 'attendance-mcp\Start-AttendanceMcp.ps1')}
}
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
        if($saved.runner -ne $runner){throw 'Another presenter backend is running. Run Stop-DigitalHuman.cmd before switching backend.'}
        Write-Output 'Digital presenter already running: http://127.0.0.1:8766'
        if($OpenBrowser){Start-Process 'http://127.0.0.1:8766'}
        return
    }
}
$logs=Join-Path $runtime ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-u',('"'+$runner+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
@{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');runner=$runner;logs=$logs} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
$deadline=(Get-Date).AddSeconds(60)
do{
    if($proc.HasExited){throw "Digital presenter exited; inspect $logs"}
    try{$health=Invoke-RestMethod 'http://127.0.0.1:8766/api/health' -TimeoutSec 3;$ready=$health.model_state -eq 'ready';if($health.model_state -eq 'error'){throw 'Presenter model failed to initialize.'}}catch{$ready=$false}
    if(-not $ready){Start-Sleep -Milliseconds 500}
}until($ready -or (Get-Date) -ge $deadline)
if(-not $ready){throw "Digital presenter startup timed out; inspect $logs"}
Write-Output 'Digital presenter ready: http://127.0.0.1:8766'
if($OpenBrowser){Start-Process 'http://127.0.0.1:8766'}
