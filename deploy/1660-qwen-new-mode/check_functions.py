"""Actual target WebRTC + realtime model + paid retrieval + native MCP acceptance."""
import asyncio,hashlib,json,sqlite3,time,wave
from pathlib import Path
import aiohttp
import cv2
import numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription
from aioice import ice

ROOT=Path('D:/XiaolinDigitalHuman');OUT=ROOT/'deployment/qwen-new-mode-20261110/reports';OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:8771';ORIGIN={'Origin':BASE}
async def main():
    report=dict(status='RUNNING',scope='Actual GTX1660-local native WebRTC, frozen voice and cloud model; physical microphone/speaker pending',cases=[])
    events=[];tasks=[];counts=dict(video=0,audio=0,voiced=0);dimensions=set();pc=None
    try:
        async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=90)) as http:
            async def get(url):
                async with http.get(url) as response:response.raise_for_status();return await response.json()
            before=await get('http://127.0.0.1:8783/health');settings=await get(BASE+'/api/settings')
            report['mcp_before']=before
            async with http.ws_connect(BASE+'/ws?scope=acceptance-1660-20261110',headers=ORIGIN) as ws:
                ready=await ws.receive_json();assert ready['type']=='ready',ready
                headers={**ORIGIN,'X-Demo-Session':ready['session_id']}
                async def post(path,data):
                    async with http.post(BASE+path,json=data,headers=headers) as response:
                        raw=await response.text();assert response.status==200,(path,response.status,raw);return json.loads(raw)
                async def read():
                    async for message in ws:
                        if message.type==aiohttp.WSMsgType.TEXT:events.append({**json.loads(message.data),'received':time.monotonic()})
                tasks.append(asyncio.create_task(read()))
                async def wait(condition,label,timeout=60):
                    end=time.monotonic()+timeout
                    while not condition():
                        if time.monotonic()>end:raise TimeoutError(label+' '+json.dumps(events[-5:],ensure_ascii=False))
                        await asyncio.sleep(.05)
                pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
                @pc.on('track')
                def ontrack(track):
                    async def consume():
                        try:
                            while True:
                                frame=await track.recv();counts[track.kind]+=1
                                if track.kind=='video':
                                    dimensions.add((frame.width,frame.height))
                                    if counts['video']==40:
                                        ok,image=cv2.imencode('.jpg',frame.to_ndarray(format='bgr24'));assert ok;(OUT/'received-frame.jpg').write_bytes(image.tobytes())
                                elif np.max(np.abs(frame.to_ndarray().astype(float)))>500:counts['voiced']+=1
                        except asyncio.CancelledError:pass
                        except Exception:pass
                    tasks.append(asyncio.create_task(consume()))
                pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer());answer=await post('/api/offer',dict(type='offer',sdp=pc.localDescription.sdp))
                await pc.setRemoteDescription(RTCSessionDescription(**answer));await wait(lambda:counts['video']>30,'media')
                async def say(text):
                    events.clear();started=time.monotonic();await ws.send_json(dict(type='text',text=text))
                    await wait(lambda:any(e['type'] in ('playback_done','error') for e in events),'reply')
                    errors=[e for e in events if e['type']=='error'];assert not errors,errors
                    answers=[e['text'] for e in events if e['type']=='assistant_text'];assert answers,events
                    result=next((e.get('result') for e in events if e['type']=='capability_result'),None)
                    row=dict(question=text,answer=answers[-1],capability=result,
                        first_text_seconds=next((e['received']-started for e in events if e['type'] in ('assistant_delta','assistant_text')),None),
                        first_play_seconds=next((e['received']-started for e in events if e['type']=='playing'),None),
                        gestures=[e['gesture'] for e in events if e['type']=='gesture'])
                    report['cases'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True);return row
                row=await say('请帮我执行一次考勤打卡测试。')
                assert row['capability']['attendance']['ok'] and '测试成功' in row['answer'],row
                row=await say('我不是要执行打卡，只想问“打卡”这个词是什么意思。')
                assert not (row['capability'] or {}).get('attendance',{}).get('executed'),row
                knowledge=await post('/api/knowledge',dict(title='1660隔离验收资料',content='本资料仅用于隔离测试，不是真实业务。小霖试验展厅周一闭馆，服务台编号是R726。'))
                try:
                    row=await say('请查询业务资料，小霖试验展厅哪天闭馆，服务台编号是什么？')
                    assert row['capability']['knowledge']['status']=='ok' and 'R726' in row['answer'],row
                finally:
                    for identifier in knowledge['ids']:
                        async with http.delete(BASE+'/api/knowledge/'+identifier,headers=headers) as response:assert response.status==200
                row=await say('请记住，我喜欢喝龙井茶，我的一体机验收代号是蓝鹊七二。')
                end=time.monotonic()+15
                while True:
                    user=hashlib.sha256(b'local-admin').hexdigest()[:24]+':acceptance-1660-20261110'
                    with sqlite3.connect(ROOT/'avatar-2d/runtime/qwen-realtime-v2/capabilities.sqlite3') as db:
                        stored=db.execute("SELECT COUNT(*) FROM documents WHERE kind='memory' AND user=? AND instr(content,?)>0",(user,'我喜欢喝龙井茶')).fetchone()[0]
                    if stored:break
                    assert time.monotonic()<end,'memory write';await asyncio.sleep(.3)
                await ws.send_json(dict(type='stop'));await asyncio.sleep(.5)
                row=await say('请检索关联记忆，我之前说喜欢喝什么茶，验收代号是什么？')
                assert row['capability']['memory']['status']=='ok' and '龙井' in row['answer'] and '蓝鹊七二' in row['answer'],row
                # New realtime connection, then paced frozen audio, not a physical microphone.
                await ws.send_json(dict(type='stop'));await asyncio.sleep(.5);events.clear();await ws.send_json(dict(type='start'))
                await wait(lambda:any(e['type']=='provider_ready' for e in events),'voice provider')
                source=ROOT/'deployment/qwen-new-mode-20261110/voice-input.wav'
                with wave.open(str(source),'rb') as audio:
                    assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(16000,1,2)
                    pcm=audio.readframes(audio.getnframes())
                events.clear();begin=time.monotonic()
                for offset in range(0,len(pcm),3200):
                    await ws.send_bytes(pcm[offset:offset+3200]);await asyncio.sleep(max(0,begin+(offset+3200)/32000-time.monotonic()))
                for _ in range(10):await ws.send_bytes(bytes(3200));await asyncio.sleep(.1)
                await wait(lambda:any(e['type']=='playback_done' for e in events),'voice response')
                voice=dict(name='frozen_voice',sha256=hashlib.sha256(source.read_bytes()).hexdigest(),events=[e for e in events if e['type'] in ('user_text','assistant_text','capability_result','error')])
                assert any(e['type']=='capability_result' and e['result']['attendance']['ok'] for e in events),voice
                report['cases'].append(voice)
                original={k:v for k,v in settings.items() if k!='revision'}
                try:
                    await post('/api/settings',{**original,'coordinator_enabled':False});await asyncio.sleep(.3)
                    off_before=await get('http://127.0.0.1:8783/health');row=await say('请执行一次考勤打卡测试。')
                    off_after=await get('http://127.0.0.1:8783/health')
                    assert off_before['call_count']==off_after['call_count'] and not row['gestures'] and row['capability'] is None,row
                finally:await post('/api/settings',original)
                report.update(dimensions=[list(x) for x in dimensions],received=counts,settings_restored=await get(BASE+'/api/settings'),mcp_after=await get('http://127.0.0.1:8783/health'))
                assert dimensions=={(1080,1920)} and counts['voiced']>0
                assert report['mcp_after']['call_count']-before['call_count']==2,report['mcp_after']
                report['status']='PASSED'
    except Exception as error:
        import traceback;traceback.print_exc();report.update(status='FAILED',error_type=type(error).__name__,error=str(error))
    finally:
        if pc:
            try:await asyncio.wait_for(pc.close(),8)
            except Exception as close_error:report['peer_close_error']=type(close_error).__name__
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        (OUT/'functions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],output=str(OUT/'functions.json'))),flush=True)
    return report['status']=='PASSED'

if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
