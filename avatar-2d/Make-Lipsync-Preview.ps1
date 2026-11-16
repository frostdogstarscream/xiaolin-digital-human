param(
    [ValidateSet('auto', 'fp32', 'fp16')][string]$Precision = 'auto',
    [ValidateRange(1, 16)][int]$BatchSize = 4,
    [ValidateRange(0, 20)][double]$Seconds = 0,
    [ValidateSet('idle', 'welcome-wave', 'goodbye-wave', 'explain-open-palms', 'acknowledge-nod')][string]$Motion = 'idle'
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner = Join-Path $PSScriptRoot 'tools\lipsync_preview.py'
$validator = Join-Path $PSScriptRoot 'tools\validate_preview.py'
if (-not (Test-Path -LiteralPath $python)) { throw 'The independent avatar-2d environment is missing.' }
$outputName = 'preview-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
& $python -u $runner --output $outputName --batch-size $BatchSize --precision $Precision --seconds $Seconds --motion $Motion
if ($LASTEXITCODE -ne 0) { throw 'Lip-sync inference failed. Retained output can be inspected.' }
& $python $validator $outputName
if ($LASTEXITCODE -ne 0) { throw 'Output media validation failed.' }
Write-Host ('Output: ' + (Join-Path $PSScriptRoot "outputs\$outputName\presenter-speaking.mp4"))
