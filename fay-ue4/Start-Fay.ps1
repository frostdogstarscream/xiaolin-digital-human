param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv-fay\Scripts\python.exe'
$runner=Join-Path $PSScriptRoot 'tools\run_fay_local.py'
$runtime=Join-Path $PSScriptRoot 'runtime\fay-local'
if(-not(Test-Path -LiteralPath $python)){throw 'Fay Python environment is missing.'}
$stateFile=Join-Path $runtime 'process.json'
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$saved.start_time_utc).ToUniversalTime().Ticks){
        Write-Output 'Fay is already running: http://127.0.0.1:5000'
        if($OpenBrowser){Start-Process 'http://127.0.0.1:5000'}
        return
    }
}
$launch=Join-Path $runtime ('launch-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $launch -Force | Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-u',('"'+$runner+'"')) -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $launch 'stdout.log') -RedirectStandardError (Join-Path $launch 'stderr.log')
@{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');python=$python;runner=$runner;logs=$launch} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
try{
    $deadline=(Get-Date).AddSeconds(90)
    $ready=$false
    do{
        Start-Sleep -Milliseconds 500
        if($proc.HasExited){throw "Fay exited during startup; inspect $launch"}
        try{
            $response=Invoke-WebRequest 'http://127.0.0.1:5000/' -UseBasicParsing -TimeoutSec 2
            $ready=$response.StatusCode -eq 200 -and $response.Content.Length -gt 1000
        }catch{$ready=$false}
    }until($ready -or (Get-Date) -ge $deadline)
    if(-not $ready){throw "Fay startup timed out; inspect $launch"}
    @{pid=$proc.Id;start_time_utc=$proc.StartTime.ToUniversalTime().ToString('o');python=$python;runner=$runner;logs=$launch} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
    Write-Output 'Fay web manager ready: http://127.0.0.1:5000'
    Write-Output 'Start the conversation core from the web manager or the digital presenter console.'
    if($OpenBrowser){Start-Process 'http://127.0.0.1:5000'}
}catch{
    if(-not $proc.HasExited){& (Join-Path $PSScriptRoot 'Stop-Fay.ps1')}
    throw
}
