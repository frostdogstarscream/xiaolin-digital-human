param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$publicRoot=Join-Path $workspace 'docs\fay-reference\public-wiki-2026-11-03'
$runtime=Join-Path $workspace 'runtime\fay-reference-reader'
$statePath=Join-Path $runtime 'process.json'
$python=Join-Path $workspace 'avatar-2d\.venv\Scripts\python.exe'
$url='http://127.0.0.1:8769/'
if(-not(Test-Path -LiteralPath (Join-Path $publicRoot 'index.html'))){throw 'Offline reference is missing.'}
if(Get-NetTCPConnection -State Listen -LocalPort 8769 -ErrorAction SilentlyContinue){
    if(-not(Test-Path -LiteralPath $statePath)){throw 'Port 8769 is already in use; retained existing service.'}
    $saved=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $proc=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if(-not $proc -or $proc.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.start).ToUniversalTime().Ticks){throw 'Reader process identity changed.'}
    Write-Output $url
    if($OpenBrowser){Start-Process $url}
    return
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-m','http.server','8769','--bind','127.0.0.1','--directory',('"'+$publicRoot+'"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log')
@{pid=$proc.Id;start=$proc.StartTime.ToUniversalTime().ToString('o');root=$publicRoot} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output $url
if($OpenBrowser){Start-Process $url}
