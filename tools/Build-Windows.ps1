param([string]$UnityEditor = $env:UNITY_EDITOR_PATH)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $UnityEditor -and (Test-Path -LiteralPath (Join-Path $projectRoot '.env.local'))) {
    $editorSetting = Get-Content -LiteralPath (Join-Path $projectRoot '.env.local') | Where-Object { $_ -match '^UNITY_EDITOR_PATH=' } | Select-Object -Last 1
    if ($editorSetting) { $UnityEditor = ($editorSetting -replace '^UNITY_EDITOR_PATH=', '').Trim().Trim('"').Trim("'") }
}
if (-not $UnityEditor) {
    $candidates = @('D:\Develop\Unity\6000.0.65f1\Editor\Unity.exe', 'C:\Program Files\Unity\Hub\Editor\6000.0.65f1\Editor\Unity.exe')
    $UnityEditor = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $UnityEditor -or -not (Test-Path -LiteralPath $UnityEditor)) { throw 'Unity 6000.0.65f1 editor not found. Set UNITY_EDITOR_PATH or pass -UnityEditor.' }
$logDir = Join-Path $projectRoot 'runtime\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$buildLog = Join-Path $logDir 'unity-build.log'
$argsList = @('-batchmode', '-nographics', '-projectPath', ('"' + (Join-Path $projectRoot 'unity') + '"'), '-executeMethod', 'HoloKiosk.Editor.KioskBuild.Windows', '-logFile', ('"' + $buildLog + '"'))
$process = Start-Process -FilePath $UnityEditor -ArgumentList $argsList -WindowStyle Hidden -PassThru
$process.WaitForExit()
if ($process.ExitCode -ne 0) { throw "Unity build failed. See $buildLog" }
Write-Output (Join-Path $projectRoot 'unity\Builds\Windows-Quaternius\HoloKiosk.exe')
