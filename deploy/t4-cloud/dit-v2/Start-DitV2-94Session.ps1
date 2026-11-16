$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = Join-Path $workspace 'avatar-2d\.venv\Scripts\python.exe'
}
$worker = Join-Path $workspace 'runtime\server-4t4\ssh-worker.py'
$control = Join-Path $workspace 'runtime\server-4t4\control-dit-v2'
Write-Host 'Connecting to 36.133.88.94:6025 (pinned ED25519 host key) for DiT-v2 50fps deployment...'
Write-Host 'Enter the SSH password locally. It stays in process memory only.'
Write-Host 'Keep this window open until deployment completes; Ctrl+C closes the session.'
& $python $worker --port 6025 --control-root $control
if ($LASTEXITCODE -ne 0) { throw 'T4 SSH session ended with an error.' }
