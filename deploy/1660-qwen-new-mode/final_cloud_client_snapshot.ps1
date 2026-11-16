$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient'
$ports=@(5000,5010,8766,8771,8780,8783)
$listeners=@(Get-NetTCPConnection -State Listen | Where-Object {$ports -contains $_.LocalPort} | Select-Object LocalPort,OwningProcess)
$profile=Join-Path $root 'BrowserProfile'
$browsers=@(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object {$_.CommandLine -and $_.CommandLine.Contains($profile) -and $_.CommandLine -notlike '*--type=*'} | Select-Object ProcessId)
$desktop=[Environment]::GetFolderPath('Desktop');$shell=New-Object -ComObject WScript.Shell;$shortcuts=@()
foreach($name in @('启动小霖新模式','停止小霖新模式','小霖网页登录信息')){
    $path=Join-Path $desktop ($name+'.lnk');$entry=$shell.CreateShortcut($path)
    $shortcuts+=@{name=$name;target=$entry.TargetPath;arguments=$entry.Arguments}
}
$old=@(Get-ScheduledTask -TaskName 'XiaolinQwenNewMode-*' | Select-Object TaskName,State)
$record=@{hostname=$env:COMPUTERNAME;mode='server-web-client';url='https://36.133.88.94:6444/';local_backend_listeners=$listeners;local_inference_tasks=$old;browser=$browsers;shortcuts=$shortcuts;credential=(Get-Content (Join-Path $root 'credential-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json);credential_acl=@((Get-Acl (Join-Path $root 'web-access.clixml')).Access | Select-Object IdentityReference,FileSystemRights,IsInherited);certificate=(Get-Content (Join-Path $root 'certificate-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json);captured=(Get-Date).ToString('o')}
if($listeners.Count){throw 'A local backend is still listening'}
if($old | Where-Object State -ne 'Disabled'){throw 'A local new-mode task is not disabled'}
if(-not $browsers.Count){throw 'Cloud-client app window was not launched'}
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root 'final-state.json') -Encoding UTF8
Write-Output 'Cloud client final state verified; no local inference service listening'
