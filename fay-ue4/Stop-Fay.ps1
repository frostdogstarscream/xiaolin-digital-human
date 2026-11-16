$ErrorActionPreference='Stop'
$stateFile=Join-Path $PSScriptRoot 'runtime\fay-local\process.json'
if(-not(Test-Path -LiteralPath $stateFile)){Write-Output 'No Fay process recorded.';return}
$saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$proc=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if(-not $proc){Write-Output 'Fay is already stopped.';return}
if($proc.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){throw 'Recorded process identity changed; no process was stopped.'}
$info=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)"
if(-not $info.CommandLine.Contains($saved.runner)){throw 'Recorded runner does not match; no process was stopped.'}
# Let native Fay save newly enabled conversation memory before stopping its process.
$nativeStatus=$null
try{$nativeStatus=Invoke-RestMethod 'http://127.0.0.1:5000/api/get-run-status' -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 3}catch{}
if($nativeStatus -and $nativeStatus.status){
    try{
        $null=Invoke-WebRequest 'http://127.0.0.1:5000/api/stop-live' -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 45
        Write-Output 'Fay core stopped gracefully; native memory save completed.'
    }catch{throw 'Native Fay shutdown failed; process retained to protect unsaved memory.'}
}
# Windows venv python.exe is a redirector which can own a base-Python child.
# Stop only descendants of the validated runner, deepest first.
$owned=@($proc.Id)
for($i=0;$i -lt $owned.Count;$i++){
    $children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($owned[$i])")
    foreach($child in $children){$owned+=[int]$child.ProcessId}
}
for($i=$owned.Count-1;$i -ge 0;$i--){
    $target=Get-Process -Id $owned[$i] -ErrorAction SilentlyContinue
    if($target){
        try{Stop-Process -InputObject $target -ErrorAction Stop}
        catch{if(Get-Process -Id $owned[$i] -ErrorAction SilentlyContinue){throw}}
    }
}
Write-Output 'Stopped the Fay runner and its own child processes.'
