$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman';$dir=Join-Path $root 'deployment\qwen-new-mode-20261110';$reports=Join-Path $dir 'reports'
$browserDir=Join-Path $env:LOCALAPPDATA 'XiaolinNewModeAcceptance'
$browser=Get-Content -LiteralPath (Join-Path $browserDir 'browser.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($browser.status -ne 'PASSED'){throw 'Actual local browser acceptance must pass first'}
foreach($name in @('browser.json','browser-local.jpg','browser-fullscreen.jpg')){Copy-Item -LiteralPath (Join-Path $browserDir $name) -Destination (Join-Path $reports $name) -Force}
$mcp=Invoke-RestMethod http://127.0.0.1:8783/health -TimeoutSec 5
$process=Get-Content -LiteralPath "$root\attendance-mcp\runtime\process.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$lines=@(Get-Content -LiteralPath (Join-Path $process.logs 'stdout.log') -Encoding UTF8 | Where-Object {$_ -ceq 'success'})
@{health=$mcp;stdout_success_lines=$lines.Count} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reports 'mcp-proof.json') -Encoding UTF8
& "$root\avatar-2d\.venv\Scripts\python.exe" -X utf8 "$dir\snapshot.py" before-stop
if($LASTEXITCODE -ne 0){throw 'State snapshot failed'}
& "$dir\Control-Qwen.ps1" -Action Stop
if(Get-NetTCPConnection -State Listen -LocalPort 8771 -ErrorAction SilentlyContinue){throw 'New mode did not stop; performance task not started'}
Start-ScheduledTask -TaskName XiaolinQwenNewMode-Performance
Write-Output 'Five-minute native 1080p performance acceptance started; no model/cloud calls'
