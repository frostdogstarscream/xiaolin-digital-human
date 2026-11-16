"""Terminal-to-T4 browser acceptance; existing HTTP credentials arrive only through SSH stdin."""
import asyncio,base64,json,os,re,sys,time,wave
from pathlib import Path
import websockets
OUT=Path(os.environ['LOCALAPPDATA'])/'XiaolinCloudClient/Acceptance';PROFILE=OUT/'BrowserProfile'
BASE='https://36.133.88.94:6444'

async def main():
    account=json.loads(sys.stdin.readline());events=[];sequence=0;session=None
    report=dict(status='RUNNING',scope='Actual GTX1660 terminal Edge -> T4 HTTPS/WSS/TURN; no local inference',cases=[],physical_microphone=False,physical_speaker=False)
    try:
        port,endpoint=(PROFILE/'DevToolsActivePort').read_text().splitlines()[:2]
        async with websockets.connect('ws://127.0.0.1:'+port+endpoint,max_size=16*1024*1024) as ws:
            async def send(method,params=None,sid=None):
                nonlocal sequence;sequence+=1;value=dict(id=sequence,method=method,params=params or {})
                if sid:value['sessionId']=sid
                await ws.send(json.dumps(value));return sequence
            async def call(method,params=None,sid=None):
                identifier=await send(method,params,sid)
                while True:
                    message=json.loads(await asyncio.wait_for(ws.recv(),25));kind=message.get('method');params=message.get('params',{})
                    if kind=='Fetch.authRequired':
                        allowed=params['request']['url'].startswith(BASE+'/')
                        auth=dict(response='ProvideCredentials',username=account['username'],password=account['password']) if allowed else dict(response='CancelAuth')
                        await send('Fetch.continueWithAuth',dict(requestId=params['requestId'],authChallengeResponse=auth),message.get('sessionId'))
                    elif kind=='Fetch.requestPaused':await send('Fetch.continueRequest',dict(requestId=params['requestId']),message.get('sessionId'))
                    if message.get('id')==identifier:
                        if 'error' in message:raise RuntimeError(str(message['error']))
                        return message.get('result',{})
            target=(await call('Target.createTarget',dict(url='about:blank')))['targetId']
            session=(await call('Target.attachToTarget',dict(targetId=target,flatten=True)))['sessionId']
            await call('Fetch.enable',dict(handleAuthRequests=True),session)
            await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=960,deviceScaleFactor=1,mobile=False),session)
            await call('Page.navigate',dict(url=BASE+'/?takeover=1&scope=acceptance-client1660-wake'),session)
            async def evaluate(expression):
                value=await call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True,userGesture=True),session)
                if value.get('exceptionDetails'):raise RuntimeError(str(value['exceptionDetails']))
                return value.get('result',{}).get('value')
            async def wait(expression,label,timeout=60):
                end=time.monotonic()+timeout
                while True:
                    result=await evaluate(expression)
                    if result:return result
                    if time.monotonic()>end:
                        debug=await evaluate("window.qwenDemo?.events.slice(-12)")
                        raise TimeoutError(label+' '+json.dumps(debug,ensure_ascii=False))
                    await asyncio.sleep(.25)
            await wait("window.qwenDemo?.pc?.connectionState==='connected'&&document.querySelector('#avatar').videoWidth===1080",'public terminal WebRTC',75)
            async def health():return await evaluate("(async()=>await(await fetch('/api/health')).json())()")
            async def snapshot():return await evaluate("({events:qwenDemo.events.filter(e=>['wake_state','wake_detected','assistant_text','capability_result','error','response_done'].includes(e.type)),wake:qwenDemo.wakeState})")
            async def clear():await evaluate('qwenDemo.events=[];true')
            async def pcm(name):
                path=OUT/name
                with wave.open(str(path),'rb') as audio:
                    assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(16000,1,2)
                    encoded=base64.b64encode(audio.readframes(audio.getnframes())).decode()
                expression="(async()=>{const s=atob("+json.dumps(encoded)+");const b=Uint8Array.from(s,c=>c.charCodeAt(0));for(let i=0;i<b.length;i+=3200){qwenDemo.ws.send(b.slice(i,i+3200));await new Promise(r=>setTimeout(r,100));}for(let i=0;i<10;i++){qwenDemo.ws.send(new Uint8Array(3200));await new Promise(r=>setTimeout(r,100));}return true;})()"
                await evaluate(expression)
            report['media']=await evaluate("(async()=>({secureContext:isSecureContext,width:document.querySelector('#avatar').videoWidth,height:document.querySelector('#avatar').videoHeight,stats:[...(await qwenDemo.pc.getStats()).values()].filter(x=>x.type==='inbound-rtp').map(x=>({kind:x.kind,framesDecoded:x.framesDecoded,bytesReceived:x.bytesReceived,packetsLost:x.packetsLost}))}))()")
            assert report['media']['secureContext']
            await evaluate("qwenDemo.ws.send(JSON.stringify({type:'listen'}));true")
            await wait("qwenDemo.events.some(e=>e.type==='listen_ready')",'listen readiness')
            await clear();await pcm('no-wake.wav')
            await wait("qwenDemo.events.some(e=>e.type==='wake_state'&&e.state==='waiting')",'negative wake recognition')
            before=await health();negative=await snapshot()
            assert before['model_connects']==0 and not before['provider_connected'] and not any(e['type'] in ('assistant_text','capability_result') for e in negative['events']),negative
            report['cases'].append(dict(name='no_wake_no_model_or_tool',status='PASSED',health=before));print('No wake: model and tools stayed off',flush=True)
            await clear();began=time.monotonic();await pcm('voice-input.wav')
            await wait("qwenDemo.events.some(e=>e.type==='playback_done')",'wake plus check-in response',70)
            positive=await snapshot();active=await health()
            assert any(e['type']=='capability_result' and e['result']['attendance'].get('ok') for e in positive['events']),positive
            assert active['model_connects']==1 and active['voice_awake'],active
            report['cases'].append(dict(name='wake_and_question_single_turn',status='PASSED',elapsed_seconds=time.monotonic()-began,result=positive,health=active));print('Wake + question: real MCP and spoken reply completed',flush=True)
            await evaluate("qwenDemo.ws.send(JSON.stringify({type:'sleep'}));true")
            await wait("qwenDemo.wakeState==='waiting'",'manual sleep')
            await clear();await pcm('word-only.wav')
            await wait("qwenDemo.events.some(e=>e.type==='playback_done')",'wake word welcome',70)
            welcome=await snapshot();spoken=[e.get('text','') for e in welcome['events'] if e['type']=='assistant_text']
            assert spoken and '我在' in spoken[-1] and not any(e['type']=='capability_result' and e['result']['attendance'].get('executed') for e in welcome['events']),welcome
            report['cases'].append(dict(name='word_only_private_welcome',status='PASSED',result=welcome));print('Word-only wake: welcome completed',flush=True)
            await clear();await pcm('no-wake.wav')
            await wait("qwenDemo.events.some(e=>e.type==='playback_done')",'awake follow-up without repeated wake',70)
            followup=await snapshot()
            assert any(e['type']=='capability_result' and e['result']['attendance'].get('ok') for e in followup['events']),followup
            report['cases'].append(dict(name='awake_followup_without_repeated_wake',status='PASSED',result=followup));print('Awake follow-up: MCP worked without repeating wake phrase',flush=True)
            await evaluate("document.querySelector('#fullscreen').click();true");await asyncio.sleep(.5)
            assert await evaluate("document.fullscreenElement===document.querySelector('.stage')")
            image=await call('Page.captureScreenshot',dict(format='jpeg',quality=85),session);(OUT/'cloud-fullscreen.jpg').write_bytes(base64.b64decode(image['data']))
            await evaluate("document.querySelector('#fullscreen').click();true")
            print('Waiting for actual 60-second return to wake standby',flush=True)
            began=time.monotonic();await wait("qwenDemo.wakeState==='waiting'",'60-second automatic sleep',76)
            sleeping=await health();assert sleeping['wake_listening'] and not sleeping['voice_awake'] and not sleeping['provider_connected'],sleeping
            report['cases'].append(dict(name='actual_timeout',status='PASSED',wait_seconds=time.monotonic()-began,health=sleeping))
            await clear();await pcm('no-wake.wav');await wait("qwenDemo.events.some(e=>e.type==='wake_state'&&e.state==='waiting')",'negative after timeout')
            final=await health();assert final['model_connects']==2 and not final['provider_connected'],final
            report.update(status='PASSED',final_health=final,fullscreen=True,tls_verification_disabled=False)
            await evaluate("qwenDemo.ws.send(JSON.stringify({type:'stop'}));true")
            try:await call('Browser.close')
            except websockets.ConnectionClosed:pass
    except Exception as error:
        message=str(error).replace(account['password'],'[redacted]')
        report.update(status='FAILED',error_type=type(error).__name__,error=message)
        print(json.dumps(dict(status='FAILED',error_type=type(error).__name__,error=message),ensure_ascii=False),flush=True)
        # The acceptance browser is a separate owned profile; release its cloud viewer even on failure.
        try:
            if session:await call('Browser.close')
        except Exception:pass
    finally:
        account.clear();(OUT/'cloud-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],report=str(OUT/'cloud-acceptance.json')),ensure_ascii=False),flush=True)
    return report['status']=='PASSED'
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
