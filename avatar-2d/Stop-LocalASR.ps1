$ErrorActionPreference='Stop'
$stateFile=Join-Path $PSScriptRoot 'runtime\asr-service\process.json'
if(-not(Test-Path -LiteralPath $stateFile)){Write-Output 'No local ASR process recorded.';return}
$saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$proc=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if(-not $proc){Write-Output 'Local ASR already stopped.';return}
if($proc.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){throw 'ASR process identity changed.'}
$info=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)"
if(-not $info.CommandLine.Contains($saved.runner)){throw 'ASR runner mismatch.'}
$owned=@($proc.Id)
for($i=0;$i -lt $owned.Count;$i++){
    foreach($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($owned[$i])")){$owned+=[int]$child.ProcessId}
}
for($i=$owned.Count-1;$i -ge 0;$i--){
    $target=Get-Process -Id $owned[$i] -ErrorAction SilentlyContinue
    if($target){try{Stop-Process -InputObject $target}catch{if(Get-Process -Id $owned[$i] -ErrorAction SilentlyContinue){throw}}}
}
Write-Output 'Local FunASR stopped.'
