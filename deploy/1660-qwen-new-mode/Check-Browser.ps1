$ErrorActionPreference='Stop'
$dir=Join-Path $env:LOCALAPPDATA 'XiaolinNewModeAcceptance'
$profile=Join-Path $dir 'NativeBrowserProfile'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$active=Join-Path $profile 'DevToolsActivePort'
if(Test-Path -LiteralPath $active){Remove-Item -LiteralPath $active}
$browser='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$arguments=@('--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',('--user-data-dir="'+$profile+'"'),'--autoplay-policy=no-user-gesture-required','about:blank')
$proc=Start-Process -FilePath $browser -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir 'edge.stdout.log') -RedirectStandardError (Join-Path $dir 'edge.stderr.log')
$report=@{status='RUNNING';browser=$browser;scope='Actual local Edge browser on GTX1660; no cloud model calls'}
$socket=$null;$script:sequence=0
function Send-Cdp([string]$Method,$Params,[string]$Session=''){
    $script:sequence++
    $request=@{id=$script:sequence;method=$Method;params=$Params}
    if($Session){$request.sessionId=$Session}
    $bytes=[Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Depth 12 -Compress))
    $segment=New-Object 'ArraySegment[byte]' -ArgumentList (,$bytes)
    $socket.SendAsync($segment,[Net.WebSockets.WebSocketMessageType]::Text,$true,[Threading.CancellationToken]::None).GetAwaiter().GetResult()
    while($true){
        $stream=New-Object IO.MemoryStream
        do{
            $buffer=New-Object byte[] 65536
            $part=New-Object 'ArraySegment[byte]' -ArgumentList (,$buffer)
            $cancellation=New-Object Threading.CancellationTokenSource(20000)
            try{$received=$socket.ReceiveAsync($part,$cancellation.Token).GetAwaiter().GetResult()}finally{$cancellation.Dispose()}
            if($received.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close){throw 'Browser closed'}
            $stream.Write($buffer,0,$received.Count)
        }while(-not $received.EndOfMessage)
        $message=[Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
        $stream.Dispose()
        if($message.id -eq $script:sequence){if($message.error){throw ($message.error | ConvertTo-Json -Compress)};return $message.result}
    }
}
function Evaluate([string]$Expression){
    $value=Send-Cdp 'Runtime.evaluate' @{expression=$Expression;returnByValue=$true;awaitPromise=$true;userGesture=$true} $script:session
    if($value.exceptionDetails){throw ($value.exceptionDetails | ConvertTo-Json -Depth 8 -Compress)}
    return $value.result.value
}
try{
    $deadline=(Get-Date).AddSeconds(30)
    while(-not (Test-Path -LiteralPath $active)){
        if((Get-Date) -gt $deadline){throw 'Edge debugging did not become ready'}
        Start-Sleep -Milliseconds 200
    }
    $portInfo=Get-Content -LiteralPath $active
    $socket=New-Object Net.WebSockets.ClientWebSocket
    $socket.ConnectAsync([uri]('ws://127.0.0.1:'+$portInfo[0]+$portInfo[1]),[Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $target=(Send-Cdp 'Target.createTarget' @{url='about:blank'}).targetId
    $script:session=(Send-Cdp 'Target.attachToTarget' @{targetId=$target;flatten=$true}).sessionId
    $null=Send-Cdp 'Emulation.setDeviceMetricsOverride' @{width=1440;height=960;deviceScaleFactor=1;mobile=$false} $script:session
    $null=Send-Cdp 'Page.navigate' @{url='http://127.0.0.1:8771/'} $script:session
    $deadline=(Get-Date).AddSeconds(75)
    do{
        $state=Evaluate '({state:window.qwenDemo?.pc?.connectionState,width:document.querySelector("#avatar")?.videoWidth,height:document.querySelector("#avatar")?.videoHeight,error:document.querySelector("#error")?.textContent})'
        if((Get-Date) -gt $deadline){throw ('Media timeout: '+($state | ConvertTo-Json -Compress))}
        if($state.state -ne 'connected' -or -not $state.width){Start-Sleep -Milliseconds 300}
    }while($state.state -ne 'connected' -or -not $state.width)
    $stats='(async()=>[...(await qwenDemo.pc.getStats()).values()].filter(s=>s.type==="inbound-rtp").map(s=>({kind:s.kind,bytesReceived:s.bytesReceived,framesDecoded:s.framesDecoded,packetsLost:s.packetsLost})))()'
    $first=Evaluate $stats;Start-Sleep -Seconds 4;$second=Evaluate $stats
    if(($second | Where-Object kind -eq video).framesDecoded -le ($first | Where-Object kind -eq video).framesDecoded){throw 'Browser video did not advance'}
    if($state.width -ne 1080 -or $state.height -ne 1920){throw 'Unexpected browser resolution'}
    $capture=Send-Cdp 'Page.captureScreenshot' @{format='jpeg';quality=85} $script:session
    [IO.File]::WriteAllBytes((Join-Path $dir 'browser-local.jpg'),[Convert]::FromBase64String($capture.data))
    $null=Evaluate 'document.querySelector("#fullscreen").click();true';Start-Sleep -Milliseconds 500
    $full=Evaluate '({active:document.fullscreenElement===document.querySelector(".stage"),label:document.querySelector("#fullscreen").textContent,fit:getComputedStyle(document.querySelector("#avatar")).objectFit})'
    if(-not $full.active -or $full.fit -ne 'contain'){throw 'Native fullscreen failed'}
    $capture=Send-Cdp 'Page.captureScreenshot' @{format='jpeg';quality=85} $script:session
    [IO.File]::WriteAllBytes((Join-Path $dir 'browser-fullscreen.jpg'),[Convert]::FromBase64String($capture.data))
    $null=Evaluate 'document.querySelector("#fullscreen").click();true';Start-Sleep -Milliseconds 300
    if(-not (Evaluate 'document.fullscreenElement===null')){throw 'Fullscreen exit failed'}
    $report.status='PASSED';$report.media=$state;$report.first=$first;$report.second=$second;$report.fullscreen=$full;$report.fullscreen_exit=$true
    try{$null=Send-Cdp 'Browser.close' @{}}catch{}
}catch{$report.status='FAILED';$report.error=$_.Exception.Message}
finally{
    if($socket){$socket.Abort();$socket.Dispose()}
    if(-not $proc.HasExited){$null=$proc.WaitForExit(5000);if(-not $proc.HasExited){Stop-Process -Id $proc.Id}}
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dir 'browser.json') -Encoding UTF8
}
if($report.status -ne 'PASSED'){exit 1}
