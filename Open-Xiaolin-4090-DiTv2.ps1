$ErrorActionPreference = 'Stop'
$sshArgs = @('-b','10.36.154.44','-o','HostKeyAlias=192.168.1.116','-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-i',"$env:USERPROFILE/.ssh/aitoy_tts_4090_ed25519",'cmcc@10.36.154.54')
& ssh @sshArgs 'schtasks /Run /TN Xiaolin-ASR-4090'
if ($LASTEXITCODE -ne 0) { throw 'Could not start Xiaolin ASR task.' }
& ssh @sshArgs 'schtasks /Run /TN Xiaolin-DiTv2-50fps-4090'
if ($LASTEXITCODE -ne 0) { throw 'Could not start Xiaolin-DiTv2-50fps-4090 task.' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 18775 -ErrorAction SilentlyContinue
if (-not $listener) {
    $tunnelArgs = @('-N','-b','10.36.154.44','-o','HostKeyAlias=192.168.1.116','-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-L','127.0.0.1:18775:127.0.0.1:18775','-i',"$env:USERPROFILE/.ssh/aitoy_tts_4090_ed25519",'cmcc@10.36.154.54')
    Start-Process -FilePath 'ssh.exe' -ArgumentList $tunnelArgs -WindowStyle Hidden
}
for ($attempt=0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:18775/api/health' -TimeoutSec 3
        if ($health.status -eq 'ready') {
            Start-Process 'http://127.0.0.1:18775/'
            Write-Host 'Xiaolin 50fps DiT-v2 (4090) opened at http://127.0.0.1:18775/. Allow microphone access, then enable sound.'
            exit 0
        }
    } catch { Start-Sleep -Seconds 2 }
}
throw 'Xiaolin DiT-v2 50fps did not become ready on port 18775. Check F:\xiaolin\dit-distill-v2\logs on the 4090 workstation.'
