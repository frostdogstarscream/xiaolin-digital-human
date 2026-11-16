$ErrorActionPreference='Stop'
$taskWorkspace=Split-Path -Parent $PSScriptRoot
$taskPython=Join-Path $taskWorkspace 'fay-ue4\.venv-fay\Scripts\python.exe'
$taskRunner=Join-Path $PSScriptRoot 'server.py'
$taskRuntime=Join-Path $PSScriptRoot 'runtime'
$taskState=Join-Path $taskRuntime 'process.json'
& (Join-Path $taskWorkspace 'fay-ue4\Start-Fay.ps1')
$taskReady=$false
if(Test-Path -LiteralPath $taskState){
    $taskSaved=Get-Content -LiteralPath $taskState -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskProcess=Get-Process -Id $taskSaved.pid -ErrorAction SilentlyContinue
    if($taskProcess -and $taskProcess.StartTime.ToUniversalTime().Ticks -eq ([datetime]$taskSaved.start_time_utc).ToUniversalTime().Ticks){
        $taskInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProcess.Id)"
        if(-not $taskInfo.CommandLine.Contains($taskRunner)){throw 'Recorded attendance process does not match.'}
        $taskReady=$true
    }
}
if(-not $taskReady){
    if(Get-NetTCPConnection -State Listen -LocalPort 8783 -ErrorAction SilentlyContinue){throw 'Port 8783 is occupied; no process was replaced.'}
    $taskLogs=Join-Path $taskRuntime ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
    $taskProcess=Start-Process -FilePath $taskPython -ArgumentList @('-u',('"'+$taskRunner+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLogs 'stdout.log') -RedirectStandardError (Join-Path $taskLogs 'stderr.log')
    @{pid=$taskProcess.Id;start_time_utc=$taskProcess.StartTime.ToUniversalTime().ToString('o');runner=$taskRunner;logs=$taskLogs} | ConvertTo-Json | Set-Content -LiteralPath $taskState -Encoding UTF8
}
$taskDeadline=(Get-Date).AddSeconds(20)
do{
    try{$taskHealth=Invoke-RestMethod http://127.0.0.1:8783/health -TimeoutSec 2;$taskReady=$taskHealth.service -eq 'attendance-mcp-placeholder'}catch{$taskReady=$false}
    if(-not $taskReady){Start-Sleep -Milliseconds 250}
}until($taskReady -or (Get-Date) -ge $taskDeadline)
if(-not $taskReady){throw 'Attendance MCP did not become ready.'}
$taskManagerDeadline=(Get-Date).AddSeconds(20)
do{
    try{$taskManagerResponse=Invoke-WebRequest http://127.0.0.1:5010/api/mcp/servers -UseBasicParsing -TimeoutSec 2;$taskManagerReady=$taskManagerResponse.StatusCode -eq 200}catch{$taskManagerReady=$false}
    if(-not $taskManagerReady){Start-Sleep -Milliseconds 250}
}until($taskManagerReady -or (Get-Date) -ge $taskManagerDeadline)
if(-not $taskManagerReady){throw 'Fay MCP manager did not become ready; the placeholder process is available for retry.'}
& $taskPython (Join-Path $PSScriptRoot 'manage.py')
if($LASTEXITCODE -ne 0){throw 'Fay MCP registration failed; inspect local logs.'}
Write-Output 'Attendance placeholder ready: http://127.0.0.1:8783/sse'
