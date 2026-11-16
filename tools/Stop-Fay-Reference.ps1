$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$statePath=Join-Path $workspace 'runtime\fay-reference-reader\process.json'
if(-not(Test-Path -LiteralPath $statePath)){return}
$saved=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$proc=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if(-not $proc){return}
if($proc.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.start).ToUniversalTime().Ticks){throw 'Reader process identity changed.'}
$info=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)"
if(-not $info.CommandLine.Contains('http.server') -or -not $info.CommandLine.Contains($saved.root)){throw 'Reader command mismatch.'}
$owned=@($proc.Id)
for($i=0;$i -lt $owned.Count;$i++){
    foreach($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($owned[$i])")){$owned+=[int]$child.ProcessId}
}
for($i=$owned.Count-1;$i -ge 0;$i--){Stop-Process -Id $owned[$i] -ErrorAction SilentlyContinue}
Write-Output 'Stopped the reference reader.'
