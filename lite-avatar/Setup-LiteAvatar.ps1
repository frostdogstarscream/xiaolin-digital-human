$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$sharedPython=Join-Path $workspace 'avatar-2d\.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $sharedPython)){throw 'Existing avatar GPU runtime is required.'}
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $python)){& $sharedPython -m venv (Join-Path $PSScriptRoot '.venv')}
$sharedSite=Join-Path $workspace 'avatar-2d\.venv\Lib\site-packages'
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot '.venv\Lib\site-packages\shared_avatar_runtime.pth'),$sharedSite+"`n",[System.Text.UTF8Encoding]::new($false))
& $python -m pip install --no-deps -r (Join-Path $PSScriptRoot 'requirements.addons.lock.txt')
if($LASTEXITCODE -ne 0){throw 'LiteAvatar addon installation failed.'}
& $python (Join-Path $PSScriptRoot 'tools\prepare_source.py')
if($LASTEXITCODE -ne 0){throw 'LiteAvatar source preparation failed.'}
& $python (Join-Path $PSScriptRoot 'tools\download_assets.py')
if($LASTEXITCODE -ne 0){throw 'LiteAvatar asset preparation failed.'}
Write-Output 'LiteAvatar environment prepared. Run Start-LiteAvatar.cmd.'
