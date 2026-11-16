$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$security=New-Object IO.Pipes.PipeSecurity
$security.SetAccessRuleProtection($true,$false)
$security.AddAccessRule((New-Object IO.Pipes.PipeAccessRule($sid,[IO.Pipes.PipeAccessRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow)))
$pipe=New-Object IO.Pipes.NamedPipeServerStream('XiaolinCloudClient-Credential-Install',[IO.Pipes.PipeDirection]::In,1,[IO.Pipes.PipeTransmissionMode]::Byte,[IO.Pipes.PipeOptions]::None,4096,4096,$security)
try{
    $pipe.WaitForConnection();$reader=New-Object IO.StreamReader($pipe,[Text.Encoding]::UTF8)
    $account=$reader.ReadLine() | ConvertFrom-Json
    if(-not $account.username -or -not $account.password){throw 'Missing authorized web credentials'}
    $secret=ConvertTo-SecureString $account.password -AsPlainText -Force
    $credential=New-Object Management.Automation.PSCredential($account.username,$secret)
    $path=Join-Path $root 'web-access.clixml'
    $credential | Export-Clixml -LiteralPath $path
    $acl=New-Object Security.AccessControl.FileSecurity
    $acl.SetOwner($sid);$acl.SetAccessRuleProtection($true,$false)
    foreach($owner in @($sid,(New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))){$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($owner,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow)))}
    Set-Acl -LiteralPath $path -AclObject $acl
    $roundtrip=Import-Clixml -LiteralPath $path
    if($roundtrip.GetNetworkCredential().Password -cne $account.password){throw 'Encrypted credential roundtrip failed'}
    @{status='SAVED';protection='Windows DPAPI CurrentUser';plaintext_file=$false;url='https://36.133.88.94:6444/';saved=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'credential-result.json') -Encoding UTF8
    $account.password=$null;$secret.Dispose();$reader.Dispose()
}finally{$pipe.Dispose()}
