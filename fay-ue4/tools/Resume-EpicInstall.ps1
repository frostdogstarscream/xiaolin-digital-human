# Resume only the official installer already selected for this project.
$ErrorActionPreference = 'Stop'
$root = Join-Path (Split-Path -Parent $PSScriptRoot) 'installers'
$url = (Get-Content -LiteralPath (Join-Path $root 'epic-source-url.txt') -Raw).Trim()
$uri = [Uri]$url
if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'epicgames-download1.akamaized.net') { throw 'Unexpected installer source' }
$target = Join-Path $root 'EpicGamesLauncherInstaller.msi'
$log = Join-Path $root 'epic-resume-install.log'
$status = Join-Path $root 'epic-install-status.json'
function Write-Status([string]$State, [string]$Detail) {
    @{ at=(Get-Date).ToString('o'); state=$State; detail=$Detail; bytes=(Get-Item -LiteralPath $target -ErrorAction SilentlyContinue).Length } |
        ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
}
try {
    Write-Status 'DOWNLOADING' 'Official MSI; resuming retained partial file'
    $success=$false
    for($attempt=1; $attempt -le 12; $attempt++) {
        & curl.exe --fail --location --continue-at - --connect-timeout 30 --max-time 180 --speed-time 45 --speed-limit 1024 --output $target $url 2>> $log
        if($LASTEXITCODE -eq 0){$success=$true;break}
        Write-Status 'DOWNLOADING' "Attempt $attempt interrupted; bytes retained for next attempt"
    }
    if(-not $success){throw 'Download retries exhausted; partial installer retained'}
    $signature=Get-AuthenticodeSignature -LiteralPath $target
    if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Epic Games') {
        throw 'Installer signature is not valid for Epic Games; no installation attempted'
    }
    Write-Status 'INSTALLING' 'Authenticode valid; installing Epic Games Launcher without restart'
    $msiLog=Join-Path $root 'epic-msi.log'
    $arguments='/i "{0}" /qn /norestart /L*v "{1}"' -f $target,$msiLog
    $process=Start-Process -FilePath msiexec.exe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if($process.ExitCode -notin @(0,3010)){throw "MSI installation failed: $($process.ExitCode)"}
    Write-Status 'MSI_COMPLETED' "MSI exit $($process.ExitCode); launcher login and UE4 install remain"
} catch {
    Write-Status 'FAILED' $_.Exception.Message
    throw
}
