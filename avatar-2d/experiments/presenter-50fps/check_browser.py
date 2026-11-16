"""Owned Edge/CDP public test, strict TLS; web credentials read into RAM only."""
import asyncio,base64,json,os,subprocess,time
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'avatar-2d/outputs/presenter-50fps'/os.environ.get('XIAOLIN_BROWSER_RUN','browser');OUT.mkdir(parents=True,exist_ok=True)
BASE='https://36.133.88.94:6444';PROFILE=OUT/'edge-profile'

async def main():
    account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text())
    edge=Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
    process=subprocess.Popen([str(edge),'--headless=new','--remote-debugging-port=0','--no-first-run','--no-proxy-server',
        '--autoplay-policy=no-user-gesture-required','--user-data-dir='+str(PROFILE),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report=dict(status='RUNNING',scope='Developer-PC Edge over public HTTPS/TURN; not physical kiosk acceptance',strict_tls=True,cases=[])
    sequence=0;last=None
    try:
        deadline=time.monotonic()+30
        while not (PROFILE/'DevToolsActivePort').exists():
            if time.monotonic()>deadline:raise TimeoutError('Edge debugger')
            await asyncio.sleep(.2)
        port,endpoint=(PROFILE/'DevToolsActivePort').read_text().splitlines()[:2]
        async with websockets.connect('ws://127.0.0.1:'+port+endpoint,max_size=20*1024*1024) as ws:
            async def send(method,params=None,sid=None):
                nonlocal sequence;sequence+=1;request=dict(id=sequence,method=method,params=params or {})
                if sid:request['sessionId']=sid
                await ws.send(json.dumps(request));return sequence
            async def call(method,params=None,sid=None):
                identifier=await send(method,params,sid)
                while True:
                    msg=json.loads(await asyncio.wait_for(ws.recv(),40));kind=msg.get('method');args=msg.get('params',{})
                    if kind=='Fetch.authRequired':
                        auth=dict(response='ProvideCredentials',username=account['username'],password=account['password']) if args['request']['url'].startswith(BASE+'/') else dict(response='CancelAuth')
                        await send('Fetch.continueWithAuth',dict(requestId=args['requestId'],authChallengeResponse=auth),msg.get('sessionId'))
                    elif kind=='Fetch.requestPaused':await send('Fetch.continueRequest',dict(requestId=args['requestId']),msg.get('sessionId'))
                    if msg.get('id')==identifier:
                        if 'error' in msg:raise RuntimeError(str(msg['error']))
                        return msg.get('result',{})
            target=(await call('Target.createTarget',dict(url='about:blank')))['targetId']
            sid=(await call('Target.attachToTarget',dict(targetId=target,flatten=True)))['sessionId']
            await call('Fetch.enable',dict(handleAuthRequests=True),sid)
            await call('Emulation.setDeviceMetricsOverride',dict(width=1280,height=1000,deviceScaleFactor=1,mobile=False),sid)
            async def evaluate(code):
                result=await call('Runtime.evaluate',dict(expression=code,returnByValue=True,awaitPromise=True,userGesture=True),sid)
                if result.get('exceptionDetails'):raise RuntimeError(str(result['exceptionDetails']))
                return result.get('result',{}).get('value')
            async def wait(code,seconds=40):
                end=time.monotonic()+seconds
                while True:
                    value=await evaluate(code)
                    if value:return value
                    if time.monotonic()>end:raise TimeoutError(code)
                    await asyncio.sleep(.2)
            await call('Page.navigate',dict(url=BASE+'/experiments/50fps/live'),sid)
            await wait("document.querySelector('button')?.textContent.includes('连接实验')")
            await evaluate("document.querySelector('button').click();true")
            await wait("window.trialMetrics?.receive?.width===1080&&pc.connectionState==='connected'",70)
            assert await evaluate('isSecureContext')
            if os.environ.get('XIAOLIN_RECONNECT_ONLY'):
                await evaluate('disconnect()');assert await evaluate('window.trialMetrics===null')
                await evaluate('connect()')
                await wait("window.trialMetrics?.receive?.frames>25&&pc.connectionState==='connected'",70)
                report.update(status='PASSED',fresh_media_after_reconnect=True)
                await evaluate('disconnect()')
                try:await call('Browser.close')
                except websockets.ConnectionClosed:pass
                return True
            if os.environ.get('XIAOLIN_BROWSER_DIAGNOSTIC'):
                phases=[]
                for phase in ('idle','speech'):
                    samples=[];before=await evaluate('window.trialMetrics.receive')
                    for i in range(30):
                        if phase=='speech' and i%10==0:await evaluate("cmd('speech')")
                        await asyncio.sleep(1);samples.append(await evaluate('window.trialMetrics'))
                    after=await evaluate('window.trialMetrics.receive')
                    phases.append(dict(phase=phase,fps=(after['frames']-before['frames'])*1000/(after['timestamp']-before['timestamp']),samples=samples))
                report['diagnostic']=phases
                report['transport']=await evaluate("(async()=>{const out=[];for(const r of (await pc.getStats()).values())if(r.type==='inbound-rtp'||(r.type==='candidate-pair'&&r.nominated))out.push(r);return out})()")
                await evaluate('disconnect()');report['status']='DIAGNOSTIC_COMPLETE'
                try:await call('Browser.close')
                except websockets.ConnectionClosed:pass
                return False
            # Frozen speech and each gesture, no cloud model calls.
            await evaluate("cmd('speech')")
            samples=[];begin=time.monotonic();before=await evaluate('window.trialMetrics.receive')
            for index,action in enumerate(['welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod']):
                await evaluate('cmd('+json.dumps(action)+')')
                for _ in range(8):
                    await asyncio.sleep(1);samples.append(await evaluate('window.trialMetrics'))
                if index<3:await evaluate("cmd('speech')")
            after=await evaluate('window.trialMetrics.receive')
            report.update(receive_fps=(after['frames']-before['frames'])*1000/(after['timestamp']-before['timestamp']),samples=samples,
                          dropped_frames=after['dropped']-before['dropped'],resolution=[after['width'],after['height']],seconds=time.monotonic()-begin)
            report['transport']=await evaluate("(async()=>{const out=[];for(const r of (await pc.getStats()).values())if(r.type==='inbound-rtp'||(r.type==='candidate-pair'&&r.nominated))out.push(r);return out})()")
            await evaluate("cmd('interrupt')")
            await wait("window.trialMetrics?.state.queue_seconds===0",10)
            shot=await call('Page.captureScreenshot',dict(format='jpeg',quality=85),sid);(OUT/'live-50fps.jpg').write_bytes(base64.b64decode(shot['data']))
            await evaluate('disconnect()');await evaluate('connect()')
            await wait("window.trialMetrics?.receive?.width===1080&&pc.connectionState==='connected'",70)
            report['reconnect']=True
            report['ice_pair']=await evaluate("(async()=>{const s=await pc.getStats();let out=[];for(const r of s.values())if(r.type==='candidate-pair'&&r.state==='succeeded'&&r.nominated){const a=s.get(r.localCandidateId),b=s.get(r.remoteCandidateId);out.push({local:a?.candidateType,remote:b?.candidateType,protocol:a?.protocol})}return out})()")
            await evaluate('disconnect()')
            report['status']='PASSED' if report['receive_fps']>=49 and report['resolution']==[1080,1920] else 'BELOW_TARGET'
            try:await call('Browser.close')
            except websockets.ConnectionClosed:pass
    except Exception as error:
        report.update(status='FAILED',error=str(error).replace(account['password'],'[redacted]'))
    finally:
        account.clear()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.terminate()
        (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('samples','diagnostic','transport')},ensure_ascii=False))
    return report['status']=='PASSED'
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
