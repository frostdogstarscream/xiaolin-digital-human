$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$player = Join-Path $projectRoot 'unity\Builds\Windows-Quaternius'
if (-not (Test-Path -LiteralPath (Join-Path $player 'HoloKiosk.exe'))) { throw 'Build the native Unity player first.' }
& $pythonExe tools/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
& $pythonExe -m pip install pyinstaller==6.13.0
& $pythonExe -m PyInstaller --noconfirm --clean --onedir --name AvatarService --distpath dist/service-build --workpath runtime/pyinstaller --specpath runtime --collect-all uvicorn tools/service_runner.py
if ($LASTEXITCODE -ne 0) { throw 'Service packaging failed.' }
$delivery = Join-Path $projectRoot 'dist\HoloKiosk-Quaternius'
New-Item -ItemType Directory -Force -Path $delivery | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $delivery 'Windows') | Out-Null
Get-ChildItem -LiteralPath $player | Copy-Item -Destination (Join-Path $delivery 'Windows') -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $delivery 'Service') | Out-Null
Get-ChildItem -LiteralPath 'dist\service-build\AvatarService' | Copy-Item -Destination (Join-Path $delivery 'Service') -Recurse -Force
foreach ($name in @('Start-Kiosk.ps1', 'Start-Kiosk.vbs', '.env.example', 'README.md', 'licenses', 'docs')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $delivery -Recurse -Force
}
Write-Output "Delivery: $delivery"
