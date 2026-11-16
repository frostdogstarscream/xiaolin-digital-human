param([ValidateSet('Start','Stop','Status','Login')][string]$Action='Start')
$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'XiaolinCloudClient'
$profile=Join-Path $root 'BrowserProfile'
$browser='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$url='https://36.133.88.94:6444/?takeover=1'
if($Action -eq 'Login'){
    $path=Join-Path $root 'web-access.clixml'
    if(-not (Test-Path -LiteralPath $path)){throw 'Saved webpage login is unavailable'}
    $credential=Import-Clixml -LiteralPath $path
    Add-Type -AssemblyName System.Windows.Forms
    $form=New-Object Windows.Forms.Form;$form.Text='小霖网页登录信息';$form.Width=440;$form.Height=220;$form.StartPosition='CenterScreen'
    $name=New-Object Windows.Forms.TextBox;$name.Left=20;$name.Top=20;$name.Width=380;$name.ReadOnly=$true;$name.Text=$credential.UserName
    $password=New-Object Windows.Forms.TextBox;$password.Left=20;$password.Top=55;$password.Width=380;$password.ReadOnly=$true;$password.UseSystemPasswordChar=$true;$password.Text=$credential.GetNetworkCredential().Password
    $copyName=New-Object Windows.Forms.Button;$copyName.Text='复制账号';$copyName.Left=20;$copyName.Top=100;$copyName.Width=110;$copyName.Add_Click({[Windows.Forms.Clipboard]::SetText($name.Text)})
    $copyPassword=New-Object Windows.Forms.Button;$copyPassword.Text='复制密码';$copyPassword.Left=145;$copyPassword.Top=100;$copyPassword.Width=110;$copyPassword.Add_Click({[Windows.Forms.Clipboard]::SetText($password.Text)})
    $close=New-Object Windows.Forms.Button;$close.Text='关闭';$close.Left=270;$close.Top=100;$close.Width=110;$close.Add_Click({$form.Close()})
    $form.Controls.AddRange(@($name,$password,$copyName,$copyPassword,$close));$null=$form.ShowDialog();$password.Text='';$form.Dispose();return
}
$owned=@(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object {$_.CommandLine -and $_.CommandLine.Contains($profile) -and $_.CommandLine -notlike '*--type=*'})
if($Action -eq 'Status'){
    @{mode='server-web-client';url=$url;browser_processes=@($owned.ProcessId);local_inference_started=$false} | ConvertTo-Json -Compress
    return
}
if($Action -eq 'Stop'){
    foreach($entry in $owned){
        $process=Get-Process -Id $entry.ProcessId -ErrorAction SilentlyContinue
        if($process){$closed=$process.CloseMainWindow();if(-not $closed){Stop-Process -Id $entry.ProcessId}}
    }
    Write-Output 'Cloud client window closed; server services remain online'
    return
}
if(-not (Test-Path -LiteralPath $browser)){throw 'Microsoft Edge is missing'}
if(-not (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq 'D160BEE768369CAD3A568F0514F529E1C66E0CFF')){throw 'Xiaolin HTTPS CA is not installed for this user'}
if($owned.Count){Write-Output 'Cloud client is already open';return}
New-Item -ItemType Directory -Path $profile -Force | Out-Null
Start-Process -FilePath $browser -ArgumentList @('--no-first-run','--no-default-browser-check','--start-maximized',('--user-data-dir="'+$profile+'"'),('--app='+$url))
Write-Output 'Opened cloud Xiaolin; no local AI service was started'
