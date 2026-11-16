$ErrorActionPreference='Stop'
$taskWorkspace=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskBefore=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'runtime\before'))
$taskManifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime\source-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskCopies=@()
foreach($taskItem in $taskManifest.files){
    $taskSource=[IO.Path]::GetFullPath((Join-Path $taskBefore $taskItem.path))
    $taskTarget=[IO.Path]::GetFullPath((Join-Path $taskWorkspace $taskItem.path))
    if(-not $taskSource.StartsWith($taskBefore+'\',[StringComparison]::OrdinalIgnoreCase) -or -not $taskTarget.StartsWith($taskWorkspace+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Restore path escaped the workspace.'}
    if((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash -ne $taskItem.before_sha256){throw 'Restore source checksum mismatch.'}
    if((Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash -ne $taskItem.after_sha256){throw 'Later source edits found; preserve them before restoring.'}
    $taskCopies+=@{source=$taskSource;target=$taskTarget}
}
& (Join-Path $taskWorkspace 'avatar-2d\Stop-DigitalHuman.ps1')
& (Join-Path $PSScriptRoot 'Stop-AttendanceMcp.ps1')
& (Join-Path $taskWorkspace 'fay-ue4\Stop-Fay.ps1')
foreach($taskCopy in $taskCopies){Copy-Item -LiteralPath $taskCopy.source -Destination $taskCopy.target -Force}
& (Join-Path $taskWorkspace 'avatar-2d\Start-DigitalHuman.ps1')
Write-Output 'Pre-attendance source restored. The placeholder registration is disabled; existing memory, credentials and assets were retained.'
