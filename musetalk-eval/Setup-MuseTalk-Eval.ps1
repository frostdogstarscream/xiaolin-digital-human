param([string]$Python='D:\Develop\Anaconda3\python.exe',[string]$ProxyUrl='')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if($ProxyUrl){$env:HTTPS_PROXY=$ProxyUrl;$env:HTTP_PROXY=$ProxyUrl}
$env:UV_LINK_MODE='copy'
$env:UV_CACHE_DIR=Join-Path $PSScriptRoot 'runtime\uv-cache'
if(-not(Test-Path -LiteralPath '.venv\Scripts\python.exe')){uv venv --python $Python .venv;if($LASTEXITCODE -ne 0){throw 'venv creation failed'}}
uv pip install --python .venv\Scripts\python.exe torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
if($LASTEXITCODE -ne 0){throw 'CUDA PyTorch installation failed'}
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'Evaluation dependency installation failed'}
& .venv\Scripts\python.exe tools\download_models.py
if($LASTEXITCODE -ne 0){throw 'Model verification failed'}
& .venv\Scripts\python.exe tools\freeze_fixtures.py
if($LASTEXITCODE -ne 0){throw 'Fixture preparation failed'}
& .venv\Scripts\python.exe tools\prepare_candidate.py
if($LASTEXITCODE -ne 0){throw 'Candidate preparation failed'}
Write-Output 'Setup complete. Run Start-MuseTalk-Eval.cmd.'
