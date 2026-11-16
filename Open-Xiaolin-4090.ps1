$ErrorActionPreference = 'Stop'
$sshArgs = @('-b','10.36.154.44','-o','HostKeyAlias=192.168.1.116','-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-i',"$env:USERPROFILE/.ssh/aitoy_tts_4090_ed25519",'cmcc@10.36.154.54')
& ssh @sshArgs 'schtasks /Run /TN Xiaolin-ASR-4090'
if ($LASTEXITCODE -ne 0) { throw 'Could not start Xiaolin ASR task.' }
& ssh @sshArgs 'schtasks /Run /TN Xiaolin-MuseTalk-4090'
if ($LASTEXITCODE -ne 0) { throw 'Could not start Xiaolin MuseTalk task.' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 18774 -ErrorAction SilentlyContinue
if (-not $listener) {
    $tunnelArgs = @('-N','-b','10.36.154.44','-o','HostKeyAlias=192.168.1.116','-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-L','127.0.0.1:18774:127.0.0.1:18774','-i',"$env:USERPROFILE/.ssh/aitoy_tts_4090_ed25519",'cmcc@10.36.154.54')
    Start-Process -FilePath 'ssh.exe' -ArgumentList $tunnelArgs -WindowStyle Hidden
}
for ($attempt=0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:18774/api/health' -TimeoutSec 3
        if ($health.lipsync_backend -ne 'musetalk') { throw 'Port 18774 belongs to a different backend.' }
        Start-Process 'http://127.0.0.1:18774/'
        Write-Host 'Xiaolin 4090 opened. Allow microphone access, then enable sound.'
        exit 0
    } catch { Start-Sleep -Seconds 2 }
}
throw 'Xiaolin did not become ready. Check F:\xiaolin\logs on the 4090 workstation.'
