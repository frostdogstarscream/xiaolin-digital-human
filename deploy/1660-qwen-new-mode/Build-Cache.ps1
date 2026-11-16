$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman';$dir=Join-Path $root 'deployment\qwen-new-mode-20261110'
$env:OPENBLAS_NUM_THREADS='1';$env:OMP_NUM_THREADS='1'
$proc=Start-Process -FilePath (Join-Path $root 'avatar-2d\.venv\Scripts\python.exe') -ArgumentList @('-X','utf8','-u',('"'+$dir+'\build_compressed_cache.py"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir 'Cache.stdout.log') -RedirectStandardError (Join-Path $dir 'Cache.stderr.log')
$proc.WaitForExit();exit $proc.ExitCode
