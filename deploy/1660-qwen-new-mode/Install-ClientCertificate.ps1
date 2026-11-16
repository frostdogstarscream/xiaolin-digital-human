$ErrorActionPreference='Stop'
$client=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient'
try{
    $file=Join-Path $client 'xiaolin-root-ca.crt'
    $cert=New-Object Security.Cryptography.X509Certificates.X509Certificate2($file)
    if($cert.Thumbprint -ne 'D160BEE768369CAD3A568F0514F529E1C66E0CFF' -or $cert.HasPrivateKey){throw 'Unexpected public CA'}
    if(-not (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $cert.Thumbprint)){$null=Import-Certificate -FilePath $file -CertStoreLocation Cert:\CurrentUser\Root}
    if(-not (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $cert.Thumbprint)){throw 'Certificate was not approved'}
    $status=$null
    try{$response=Invoke-WebRequest 'https://36.133.88.94:6444/' -UseBasicParsing -TimeoutSec 15;$status=[int]$response.StatusCode}catch{if($_.Exception.Response){$status=[int]$_.Exception.Response.StatusCode}else{throw}}
    if($status -notin @(200,401)){throw ('Unexpected HTTPS status: '+$status)}
    @{status='PASSED';tls_verified=$true;http_status=$status;thumbprint=$cert.Thumbprint;installed=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $client 'certificate-result.json') -Encoding UTF8
}catch{
    @{status='NOT_INSTALLED';error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $client 'certificate-result.json') -Encoding UTF8
    throw
}
