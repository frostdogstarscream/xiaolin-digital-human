"""Actual local Chromium/Edge browser on the target; no remote debugging exposed to LAN."""
import asyncio,base64,json,os,subprocess,time,urllib.request
from pathlib import Path
import websockets
ROOT=Path('D:/XiaolinDigitalHuman');OUT=ROOT/'deployment/qwen-new-mode-20261110/reports'
PROFILE=Path(os.environ['LOCALAPPDATA'])/'XiaolinNewModeAcceptance/BrowserProfile'

async def main():
    executables=[Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),Path('C:/Program Files/Microsoft/Edge/Application/msedge.exe')]
    browser=next(p for p in executables if p.exists());PROFILE.mkdir(parents=True,exist_ok=True)
    active=PROFILE/'DevToolsActivePort';active.unlink(missing_ok=True)
    console=(OUT/'browser-console.log').open('ab')
    proc=subprocess.Popen([str(browser),'--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+str(PROFILE),'--autoplay-policy=no-user-gesture-required','about:blank'],creationflags=subprocess.CREATE_NO_WINDOW,stdout=console,stderr=console)
    report=dict(status='RUNNING',browser=str(browser),scope='Actual browser on GTX1660 host; no cloud model calls')
    try:
        end=time.monotonic()+30
        while not active.exists():
            assert proc.poll() is None,'Browser exited before readiness: '+str(proc.returncode)
            assert time.monotonic()<end,'Browser debugging readiness';await asyncio.sleep(.2)
        port,endpoint=active.read_text().splitlines()[:2]
        async with websockets.connect('ws://127.0.0.1:'+port+endpoint,max_size=12*1024*1024) as ws:
            sequence=0
            async def call(method,params=None,session=None):
                nonlocal sequence;sequence+=1;request=dict(id=sequence,method=method,params=params or {})
                if session:request['sessionId']=session
                await ws.send(json.dumps(request))
                while True:
                    value=json.loads(await asyncio.wait_for(ws.recv(),20))
                    if value.get('id')==sequence:
                        assert 'error' not in value,value;return value.get('result',{})
            target=(await call('Target.createTarget',dict(url='about:blank')))['targetId']
            session=(await call('Target.attachToTarget',dict(targetId=target,flatten=True)))['sessionId']
            await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=960,deviceScaleFactor=1,mobile=False),session)
            await call('Page.navigate',dict(url='http://127.0.0.1:8771/'),session)
            async def evaluate(expression):
                result=await call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True,userGesture=True),session)
                assert not result.get('exceptionDetails'),result;return result.get('result',{}).get('value')
            end=time.monotonic()+75
            while True:
                state=await evaluate("({state:window.qwenDemo?.pc?.connectionState,width:document.querySelector('#avatar')?.videoWidth,height:document.querySelector('#avatar')?.videoHeight,error:document.querySelector('#error')?.textContent})")
                if state.get('state')=='connected' and state.get('width'):break
                assert time.monotonic()<end,state;await asyncio.sleep(.3)
            async def stats():return await evaluate("(async()=>[...(await qwenDemo.pc.getStats()).values()].filter(s=>s.type==='inbound-rtp').map(s=>({kind:s.kind,bytesReceived:s.bytesReceived,framesDecoded:s.framesDecoded,packetsLost:s.packetsLost})))()")
            first=await stats();await asyncio.sleep(4);second=await stats()
            assert next(s for s in second if s['kind']=='video')['framesDecoded']>next(s for s in first if s['kind']=='video')['framesDecoded']
            assert (state['width'],state['height'])==(1080,1920)
            capture=await call('Page.captureScreenshot',dict(format='jpeg',quality=85),session);(OUT/'browser-local.jpg').write_bytes(base64.b64decode(capture['data']))
            await evaluate("document.querySelector('#fullscreen').click();true");await asyncio.sleep(.5)
            full=await evaluate("({active:document.fullscreenElement===document.querySelector('.stage'),label:document.querySelector('#fullscreen').textContent,fit:getComputedStyle(document.querySelector('#avatar')).objectFit})")
            assert full['active'] and full['label']=='退出全屏' and full['fit']=='contain',full
            capture=await call('Page.captureScreenshot',dict(format='jpeg',quality=85),session);(OUT/'browser-fullscreen.jpg').write_bytes(base64.b64decode(capture['data']))
            await evaluate("document.querySelector('#fullscreen').click();true");await asyncio.sleep(.3)
            assert await evaluate('document.fullscreenElement===null')
            report.update(status='PASSED',media=state,first=first,second=second,fullscreen=full,fullscreen_exit=True)
            try:await call('Browser.close')
            except websockets.ConnectionClosed:pass
    except Exception as error:
        import traceback;traceback.print_exc();report.update(status='FAILED',error_type=type(error).__name__,error=str(error))
    finally:
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
        console.close()
        (OUT/'browser.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
    return report['status']=='PASSED'
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
