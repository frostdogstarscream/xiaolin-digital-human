$ErrorActionPreference='Stop'
$stateFile=Join-Path $PSScriptRoot 'runtime\process.json'
if(-not(Test-Path -LiteralPath $stateFile)){Write-Output 'No evaluation process recorded.';return}
$saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$process=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if(-not $process){Write-Output 'Evaluation already stopped.';return}
if($process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){throw 'Process identity changed.'}
$info=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if(-not $info.CommandLine.Contains($saved.runner)){throw 'Evaluation runner mismatch.'}
$owned=@($process.Id)
for($i=0;$i -lt $owned.Count;$i++){foreach($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($owned[$i])")){$owned+=[int]$child.ProcessId}}
for($i=$owned.Count-1;$i -ge 0;$i--){Stop-Process -Id $owned[$i] -ErrorAction SilentlyContinue}
Write-Output 'Stopped evaluation and its own child processes.'
