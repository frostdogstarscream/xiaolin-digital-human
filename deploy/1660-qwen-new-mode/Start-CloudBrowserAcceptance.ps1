$ErrorActionPreference='Stop'
$dir=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient\Acceptance'
$profile=Join-Path $dir 'BrowserProfile'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$active=Join-Path $profile 'DevToolsActivePort'
if(Test-Path -LiteralPath $active){Remove-Item -LiteralPath $active}
$browser='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$proc=Start-Process -FilePath $browser -ArgumentList @('--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',('--user-data-dir="'+$profile+'"'),'--autoplay-policy=no-user-gesture-required','about:blank') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir 'edge.stdout.log') -RedirectStandardError (Join-Path $dir 'edge.stderr.log')
$proc.WaitForExit()
