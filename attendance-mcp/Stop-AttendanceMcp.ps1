param([switch]$KeepRegistration)
$ErrorActionPreference='Stop'
$taskWorkspace=Split-Path -Parent $PSScriptRoot
if(-not $KeepRegistration){
    & (Join-Path $taskWorkspace 'fay-ue4\.venv-fay\Scripts\python.exe') (Join-Path $PSScriptRoot 'manage.py') --disable
    if($LASTEXITCODE -ne 0){
        $taskMarker=Join-Path $PSScriptRoot 'runtime\registration.json'
        if(Test-Path -LiteralPath $taskMarker){
            $taskRegistration=Get-Content -LiteralPath $taskMarker -Raw -Encoding UTF8 | ConvertFrom-Json
            $taskRegistration.enabled=$false
            $taskMarkerJson=$taskRegistration | ConvertTo-Json -Depth 5
            [IO.File]::WriteAllText($taskMarker,$taskMarkerJson,[Text.UTF8Encoding]::new($false))
        }
        Write-Warning 'Fay management is unavailable. Local autostart was disabled; only the owned placeholder process will stop.'
    }
}
$taskState=Join-Path $PSScriptRoot 'runtime\process.json'
if(-not(Test-Path -LiteralPath $taskState)){return}
$taskSaved=Get-Content -LiteralPath $taskState -Raw -Encoding UTF8 | ConvertFrom-Json
$taskProcess=Get-Process -Id $taskSaved.pid -ErrorAction SilentlyContinue
if(-not $taskProcess){return}
if($taskProcess.StartTime.ToUniversalTime().Ticks -ne ([datetime]$taskSaved.start_time_utc).ToUniversalTime().Ticks){throw 'Attendance PID identity changed.'}
$taskInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProcess.Id)"
if(-not $taskInfo.CommandLine.Contains($taskSaved.runner)){throw 'Attendance runner mismatch.'}
$taskOwned=@($taskProcess.Id)
for($taskIndex=0;$taskIndex -lt $taskOwned.Count;$taskIndex++){
    foreach($taskChild in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskOwned[$taskIndex])")){$taskOwned+=[int]$taskChild.ProcessId}
}
for($taskIndex=$taskOwned.Count-1;$taskIndex -ge 0;$taskIndex--){Stop-Process -Id $taskOwned[$taskIndex] -ErrorAction SilentlyContinue}
Write-Output 'Attendance placeholder stopped.'
