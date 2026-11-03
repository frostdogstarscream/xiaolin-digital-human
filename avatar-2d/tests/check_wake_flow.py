"""Real wake sample -> local ASR -> deterministic welcome -> Fay chat -> RTC."""
import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
from wake_word import WakeGate,settings,DEFAULT_REPLY


def gate_checks():
    c=dict(enabled=True,word='小霖小霖',reply=DEFAULT_REPLY,timeout=60)
    gate=WakeGate()
    assert gate.accept('你好',c,100)['status']=='waiting'
    assert gate.accept('小霖',c,100)['status']=='waiting'
    assert gate.accept('小霖，小霖。',c,100)['status']=='waking'
    assert gate.accept('介绍自己',c,159)['status']=='question'
    assert gate.accept('你好',c,220)['status']=='waiting'
    assert gate.accept('小霖小霖，请介绍自己',c,230)['question']=='请介绍自己'
    gate.reset()
    assert gate.accept('你好',{**c,'enabled':False},300)['status']=='question'
    assert gate.accept('小林啊小林。',settings(),300)['status']=='waking'


async def main():
    gate_checks()
    report=dict(physical_microphone_verified=False,input_kind='Bailian synthetic wake-word WAV',gate_checks=True)
    base='http://127.0.0.1:8766'
    sample=Path(json.loads((ROOT/'runtime/wake-sample.json').read_text(encoding='utf-8'))['path'])
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=100)) as http:
        async with http.ws_connect(base+'/ws') as socket:
            initial=await socket.receive_json();events=[]
            async def reader():
                async for msg in socket:
                    if msg.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(msg.data))
            reading=asyncio.create_task(reader())
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':initial['client_id']}
            async def post(path,data=None):
                async with http.post(base+'/api/'+path,json=data or {},headers=headers) as response:
                    raw=await response.text();assert response.status==200,(path,response.status,raw)
                    return json.loads(raw)
            async def state():return await post('voice-state')
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));consumers=[]
            counts=dict(audio=0,video=0,voiced=0)
            @pc.on('track')
            def track_added(track):
                async def consume():
                    try:
                        while True:
                            frame=await track.recv();counts[track.kind]+=1
                            if track.kind=='audio' and np.max(np.abs(frame.to_ndarray().astype(float)))>500:counts['voiced']+=1
                    except Exception:pass
                consumers.append(asyncio.create_task(consume()))
            pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
            try:
                await pc.setLocalDescription(await pc.createOffer())
                answer=await post('offer',{'type':'offer','sdp':pc.localDescription.sdp})
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
                deadline=time.monotonic()+20
                while pc.connectionState!='connected':
                    assert time.monotonic()<deadline;await asyncio.sleep(.1)
                await post('start')
                for route in ('voice-input','voice-sleep','voice-state'):
                    async with http.post(base+'/api/'+route,json={'text':'小霖小霖'},headers={'X-Avatar-Client':'1'}) as r:
                        assert r.status==409,(route,r.status)
                assert not (await state())['awake']
                assert (await post('voice-input',{'text':'请介绍你自己'}))['status']=='waiting'
                assert not (await state())['busy']
                report['asleep_question_blocked']=True
                async with http.post(base+'/api/asr',data=sample.read_bytes(),headers=headers) as response:
                    assert response.status==200;recognized=await response.json()
                report['asr']=recognized
                decision=await post('voice-input',{'text':recognized['text']})
                assert decision['status']=='waking' and decision['welcome']==DEFAULT_REPLY,decision
                assert not decision['question'],decision
                deadline=time.monotonic()+75
                while (await state())['busy']:
                    assert time.monotonic()<deadline,events[-8:];await asyncio.sleep(.3)
                assert (await state())['awake']
                welcomes=[e for e in events if e['event']=='playback_ended']
                assert ''.join(e['text'] for e in welcomes)==DEFAULT_REPLY,welcomes
                assert counts['voiced']>10,counts
                report['welcome']={'text':DEFAULT_REPLY,'playback_completed':True,'received':counts.copy()}
                print('PASS synthetic wake ASR -> welcome speech -> RTC -> awake',flush=True)
                voiced=counts['voiced'];events.clear()
                assert (await post('voice-input',{'text':'请只用十个字回答：你可以做什么？'}))['status']=='question'
                deadline=time.monotonic()+90
                while (await state())['busy']:
                    assert time.monotonic()<deadline,events[-8:];await asyncio.sleep(.3)
                assert counts['voiced']>voiced,counts
                assert any(e['event']=='answer_complete' for e in events),events[-8:]
                assert not any(e['event']=='error' for e in events),events[-8:]
                report['followup']={'answer':next(e['text'] for e in events if e['event']=='answer_complete'),
                    'playback_completed':True,'still_awake':(await state())['awake']}
                await post('voice-sleep')
                assert not (await state())['awake']
                report['sleep_cancels_and_resets']=True
                print('PASS awake follow-up -> Qwen -> Bailian TTS -> RTC -> explicit sleep',flush=True)
            finally:
                await pc.close()
                for task in consumers+[reading]:task.cancel()
                await asyncio.gather(*consumers,reading,return_exceptions=True)
    report['status']='WAKE_WELCOME_FOLLOWUP_PASSED'
    (ROOT/'docs/wake-validation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],flush=True)


if __name__=='__main__':asyncio.run(main())
