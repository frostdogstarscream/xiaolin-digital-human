param([ValidateSet('Functions','Performance','Browser')][string]$Mode)
$ErrorActionPreference='Stop'
$root='D:\XiaolinDigitalHuman';$dir=Join-Path $root 'deployment\qwen-new-mode-20261110'
$env:OMP_NUM_THREADS='1';$env:OPENBLAS_NUM_THREADS='1';$env:MKL_NUM_THREADS='1'
$env:XIAOLIN_PRECISION='fp32';$env:XIAOLIN_VIDEO_ENCODER='h264_nvenc'
$env:PYTHONUTF8='1';$env:HF_HUB_OFFLINE='1';$env:MODELSCOPE_OFFLINE='1'
if($Mode -eq 'Performance'){
    $script=Join-Path $root 'avatar-2d\experiments\presenter-v2-1080\check_1660_sustained.py'
    $env:XIAOLIN_EVAL_OUTPUT=Join-Path $dir 'reports\performance';$env:XIAOLIN_EVAL_SECONDS='300'
}elseif($Mode -eq 'Browser'){$script=Join-Path $dir 'check_browser.py'}else{$script=Join-Path $dir 'check_functions.py'}
$proc=Start-Process -FilePath (Join-Path $root 'avatar-2d\.venv\Scripts\python.exe') -ArgumentList @('-X','utf8','-u',('"'+$script+'"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir ($Mode+'.stdout.log')) -RedirectStandardError (Join-Path $dir ($Mode+'.stderr.log'))
$proc.WaitForExit();exit $proc.ExitCode
