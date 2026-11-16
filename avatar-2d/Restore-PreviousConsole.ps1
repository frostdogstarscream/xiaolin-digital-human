$ErrorActionPreference='Stop'
$taskWorkspace=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskDirectory=Join-Path $PSScriptRoot 'runtime\automatic-gestures'
$taskManifest=Get-Content -LiteralPath (Join-Path $taskDirectory 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskFiles=@()
foreach($taskItem in $taskManifest.files){
    $taskTarget=[IO.Path]::GetFullPath((Join-Path $taskWorkspace $taskItem.path))
    $taskSource=[IO.Path]::GetFullPath((Join-Path (Join-Path $taskDirectory 'before') $taskItem.path))
    if(-not $taskTarget.StartsWith($taskWorkspace+'\',[StringComparison]::OrdinalIgnoreCase) -or -not $taskSource.StartsWith($taskDirectory+'\before\',[StringComparison]::OrdinalIgnoreCase)){throw 'Rollback path escaped the workspace.'}
    if((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash -ne $taskItem.before_sha256){throw 'Rollback source checksum mismatch.'}
    if((Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash -ne $taskItem.after_sha256){throw "Source changed after release; preserve later edits before rollback: $($taskItem.path)"}
    $taskFiles+=@{source=$taskSource;target=$taskTarget}
}
& (Join-Path $PSScriptRoot 'Stop-DigitalHuman.ps1')
& (Join-Path $taskWorkspace 'fay-ue4\Stop-Fay.ps1')
foreach($taskFile in $taskFiles){Copy-Item -LiteralPath $taskFile.source -Destination $taskFile.target -Force}
& (Join-Path $PSScriptRoot 'Start-DigitalHuman.ps1')
Write-Output 'Previous console restored. Credentials, dialogue history, memory and motion assets were retained.'
