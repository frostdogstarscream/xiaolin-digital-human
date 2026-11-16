param([string]$EngineRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\UE-Environment.ps1')
$environment = Get-KioskUEEnvironment -EngineRoot $EngineRoot -ProjectRoot $PSScriptRoot
$engine = $environment.Engine
$project = $environment.Project
$build = Join-Path $engine 'Engine\Build\BatchFiles\Build.bat'
$editor = Join-Path $engine 'Engine\Binaries\Win64\UE4Editor-Cmd.exe'
$uat = Join-Path $engine 'Engine\Build\BatchFiles\RunUAT.bat'
foreach ($file in @($build,$editor,$uat)) { if (-not (Test-Path -LiteralPath $file)) { throw "Missing engine file: $file" } }
& $build HoloKioskEditor Win64 Development $project -WaitMutex -NoHotReload -NoUBTMakefiles
if ($LASTEXITCODE -ne 0) { throw "Editor compilation failed: $LASTEXITCODE" }
$stageScript = Join-Path $environment.Root 'tools\ue_create_stage.py'
& $editor $project -run=pythonscript "-script=$stageScript" -unattended -nosplash -NullRHI
if ($LASTEXITCODE -ne 0) { throw "Stage preparation failed: $LASTEXITCODE" }
$output = Join-Path $PSScriptRoot ('dist\ue4-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $uat BuildCookRun "-project=$project" -noP4 -platform=Win64 -clientconfig=Development -build -cook -stage -pak -archive "-archivedirectory=$output" -utf8output
if ($LASTEXITCODE -ne 0) { throw "Packaging failed: $LASTEXITCODE" }
$executables = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'HoloKiosk.exe')
if ($executables.Count -eq 0) { throw 'Packaging returned success but no HoloKiosk.exe was found.' }
$executables | Select-Object FullName,Length
Write-Output 'Build complete. Visual, audio, cloud and target-device acceptance remain separate.'
