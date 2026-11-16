$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman'
$control=Join-Path $root 'deployment\qwen-new-mode-20261110\Control-Qwen.ps1'
$principal=New-ScheduledTaskPrincipal -UserId ($env:COMPUTERNAME+'\'+$env:USERNAME) -LogonType Interactive -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$shell=New-Object -ComObject WScript.Shell
foreach($operation in @('Start','Stop')){
    $name='XiaolinQwenNewMode-'+$operation
    $arguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$control+'" -Action '+$operation
    $existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if($existing -and $existing.Actions.Arguments -notlike ('*'+$control+'*')){throw ('Unrelated task exists: '+$name)}
    $action=New-ScheduledTaskAction -Execute powershell.exe -Argument $arguments -WorkingDirectory $root
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Description 'Manual Xiaolin Qwen realtime new mode' -Force | Out-Null
    $label=if($operation -eq 'Start'){'启动小霖新模式'}else{'停止小霖新模式'}
    $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ($label+'.lnk')))
    $shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\schtasks.exe';$shortcut.Arguments='/Run /TN "'+$name+'"';$shortcut.WorkingDirectory=$root;$shortcut.WindowStyle=7;$shortcut.Save()
}
Write-Output 'Manual new-mode tasks and desktop shortcuts registered'
