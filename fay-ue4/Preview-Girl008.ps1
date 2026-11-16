param([string]$EngineRoot, [switch]$SkipImport, [string]$Manifest)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\UE-Environment.ps1')
$environment = Get-KioskUEEnvironment -EngineRoot $EngineRoot -ProjectRoot $PSScriptRoot
$engine = $environment.Engine
$project = $environment.Project
$source = $environment.Root
$editor = Join-Path $engine 'Engine\Binaries\Win64\UE4Editor.exe'
$commandlet = Join-Path $engine 'Engine\Binaries\Win64\UE4Editor-Cmd.exe'
& (Join-Path $engine 'Engine\Build\BatchFiles\Build.bat') HoloKioskEditor Win64 Development $project -WaitMutex -NoHotReload -NoUBTMakefiles
if ($LASTEXITCODE -ne 0) { throw "UE C++ compilation failed: $LASTEXITCODE" }
& $commandlet $project -run=pythonscript "-script=$(Join-Path $source 'tools\ue_create_stage.py')" -unattended -nosplash -NullRHI
if ($LASTEXITCODE -ne 0) { throw 'Stage creation failed' }
if (-not $SkipImport) {
    & $commandlet $project -run=pythonscript "-script=$(Join-Path $source 'tools\ue_preview_girl008.py')" -unattended -nosplash -NullRHI
    if ($LASTEXITCODE -ne 0) { throw 'Preview import failed; inspect UE logs before retrying with a new asset id' }
}
$previewManifest = if($Manifest){(Resolve-Path -LiteralPath $Manifest).Path}else{Join-Path $source 'assets\girl008-actions-preview-v2.json'}
if (-not (Test-Path -LiteralPath $previewManifest)) { $previewManifest = Join-Path $source 'ue4\Saved\girl008_preview_v1-preview.json' }
if (-not (Test-Path -LiteralPath $previewManifest)) { throw 'Preview entry was not produced by the importer' }
# Visible window is the requested interactive character preview. No service is started.
& $editor $project /Game/Kiosk/Stage -game -windowed -ResX=600 -ResY=900 -dx11 "-CharacterPreview=$previewManifest" "-abslog=$(Join-Path $source 'runtime\preview-latest.log')"
