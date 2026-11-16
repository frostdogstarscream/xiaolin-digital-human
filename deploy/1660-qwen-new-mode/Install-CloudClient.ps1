param([switch]$SkipCertificateImport)
$ErrorActionPreference='Stop'
$stage='D:\XiaolinDigitalHuman\deployment\qwen-new-mode-20261110'
$client=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient'
New-Item -ItemType Directory -Path $client -Force | Out-Null
$certificate=New-Object Security.Cryptography.X509Certificates.X509Certificate2((Join-Path $stage 'xiaolin-root-ca.crt'))
if($certificate.Thumbprint -ne 'D160BEE768369CAD3A568F0514F529E1C66E0CFF' -or $certificate.HasPrivateKey){throw 'Unexpected HTTPS certificate'}
$algorithm=[Security.Cryptography.SHA256]::Create()
$digest=([BitConverter]::ToString($algorithm.ComputeHash($certificate.RawData))).Replace('-','').ToLowerInvariant();$algorithm.Dispose()
if($digest -ne '68ac90e1e5160e8cc51834ba44f85311e6cb231e6283668ac46e57080d755d56'){throw 'HTTPS CA digest mismatch'}
Copy-Item -LiteralPath (Join-Path $stage 'xiaolin-root-ca.crt') -Destination (Join-Path $client 'xiaolin-root-ca.crt') -Force
if(-not $SkipCertificateImport -and -not (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $certificate.Thumbprint)){
    $null=Import-Certificate -FilePath (Join-Path $client 'xiaolin-root-ca.crt') -CertStoreLocation Cert:\CurrentUser\Root
}
Copy-Item -LiteralPath (Join-Path $stage 'Control-CloudClient.ps1') -Destination (Join-Path $client 'Control-CloudClient.ps1') -Force
$desktop=[Environment]::GetFolderPath('Desktop');$backup=Join-Path $client 'PreviousLocalShortcuts'
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$shell=New-Object -ComObject WScript.Shell
foreach($action in @('Start','Stop')){
    $label=if($action -eq 'Start'){'启动小霖新模式'}else{'停止小霖新模式'}
    $path=Join-Path $desktop ($label+'.lnk')
    if((Test-Path -LiteralPath $path) -and -not (Test-Path -LiteralPath (Join-Path $backup ($label+'.lnk')))){Copy-Item -LiteralPath $path -Destination (Join-Path $backup ($label+'.lnk'))}
    $shortcut=$shell.CreateShortcut($path);$shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$client+'\Control-CloudClient.ps1" -Action '+$action
    $shortcut.WorkingDirectory=$client;$shortcut.WindowStyle=7;$shortcut.Save()
}
foreach($task in @(Get-ScheduledTask -TaskName 'XiaolinQwenNewMode-*' -ErrorAction SilentlyContinue)){
    $arguments=($task.Actions.Arguments -join ' ')
    if($arguments.Contains('qwen-new-mode-20261110') -or $arguments.Contains('XiaolinNewModeAcceptance')){Disable-ScheduledTask -TaskName $task.TaskName | Out-Null}
}
$trusted=[bool](Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $certificate.Thumbprint)
$status=$null
if($trusted){
    try{$response=Invoke-WebRequest 'https://36.133.88.94:6444/' -UseBasicParsing -TimeoutSec 15;$status=[int]$response.StatusCode}
    catch{if($_.Exception.Response){$status=[int]$_.Exception.Response.StatusCode}else{throw}}
    if($status -notin @(200,401)){throw ('Unexpected HTTPS status: '+$status)}
}
@{mode='server-web-client';url='https://36.133.88.94:6444/';tls_verified=$trusted;http_status=$status;ca_thumbprint=$certificate.Thumbprint;local_inference_enabled=$false;service_credentials_copied=$false;desktop=$desktop;installed=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $client 'installation.json') -Encoding UTF8
Write-Output 'Cloud client shortcuts installed; local backend tasks disabled'
