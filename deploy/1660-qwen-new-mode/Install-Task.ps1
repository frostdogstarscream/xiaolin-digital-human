$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman'
$dir=Join-Path $root 'deployment\qwen-new-mode-20261110'
$proc=Start-Process -FilePath (Join-Path $root 'avatar-2d\.venv\Scripts\python.exe') -ArgumentList @('-X','utf8','-u',('"'+$dir+'\install.py"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir 'install.stdout.log') -RedirectStandardError (Join-Path $dir 'install.stderr.log')
$proc.WaitForExit();exit $proc.ExitCode
