$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$worker = Join-Path $workspace 'runtime\server-4t4\ssh-worker.py'
$control = Join-Path $workspace 'runtime\server-4t4\control-eval-20261111'
Write-Host 'Connect to the existing T4 server with its pinned host key.'
Write-Host 'Enter the SSH password locally. It stays in process memory only.'
Write-Host 'Keep this window open during the evaluation; Ctrl+C closes the session.'
& $python $worker --port 6025 --control-root $control
if ($LASTEXITCODE -ne 0) { throw 'T4 evaluation SSH session ended with an error.' }
