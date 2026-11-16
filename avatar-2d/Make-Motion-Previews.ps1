param([ValidateSet('auto', 'fp32', 'fp16')][string]$Precision = 'auto')
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner = Join-Path $PSScriptRoot 'tools\lipsync_preview.py'
$validator = Join-Path $PSScriptRoot 'tools\validate_preview.py'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
foreach ($motion in @('welcome-wave', 'goodbye-wave', 'explain-open-palms', 'acknowledge-nod')) {
    $outputName = "motion-$stamp-$motion"
    & $python -u $runner --output $outputName --motion $motion --batch-size 4 --precision $Precision
    if ($LASTEXITCODE -ne 0) { throw "Motion inference failed: $motion" }
    & $python $validator $outputName
    if ($LASTEXITCODE -ne 0) { throw "Motion validation failed: $motion" }
    Write-Host ('Output: ' + (Join-Path $PSScriptRoot "outputs\$outputName\presenter-speaking.mp4"))
}
