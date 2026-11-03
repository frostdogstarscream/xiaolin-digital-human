"""Real local FunASR -> Fay/Bailian -> Qwen TTS -> LiveTalking WebRTC check."""
import asyncio
import io
import json
import time
from pathlib import Path

import aiohttp
import numpy as np
import soundfile as sf
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'
SAMPLE=ROOT.parent/'fay-ue4/runtime/fay-local/app/samples/bailian-4d5c8233594740b285bb34d25bda1c98.wav'


async def main():
    report={'input_kind':'synthetic Chinese speech; not physical microphone', 'physical_microphone_verified':False}
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=90)) as http:
        async def health():
            async with http.get(BASE+'/api/health') as response:return await response.json()
        async with http.ws_connect(BASE+'/ws') as socket:
            state=await socket.receive_json()
            events=[]
            async def reader():
                async for msg in socket:
                    if msg.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(msg.data))
            reader_task=asyncio.create_task(reader())
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':state['client_id']}
            async def post(path,data=None):
                async with http.post(BASE+'/api/'+path,json=data or {},headers=headers) as response:
                    raw=await response.text();assert response.status==200,(path,response.status,raw)
                    return json.loads(raw)
            h=await health()
            assert h['asr']['state']=='ready' and h['speech']['provider']=='bailian',h
            if not h['fay_core']:await post('start')
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
            counts={'video':0,'audio':0,'voiced':0}
            consumers=[]
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
            await pc.setLocalDescription(await pc.createOffer())
            answer=await post('offer',{'type':'offer','sdp':pc.localDescription.sdp})
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
            deadline=time.monotonic()+20
            while pc.connectionState!='connected':
                assert time.monotonic()<deadline;await asyncio.sleep(.1)
            try:
                async with http.post(BASE+'/api/asr',data=SAMPLE.read_bytes(),headers={'X-Avatar-Client':'1'}) as response:
                    assert response.status==409
                async with http.post(BASE+'/api/asr',data=SAMPLE.read_bytes(),headers=headers) as response:
                    assert response.status==200,await response.text()
                    recognized=await response.json()
                assert '欢迎' in recognized['text'] and '展厅' in recognized['text'],recognized
                report['asr']=recognized
                print('PASS real local ASR:',json.dumps(recognized,ensure_ascii=False),flush=True)
                async with http.ws_connect('http://127.0.0.1:8780/') as fay_asr:
                    await fay_asr.send_json({'vad_need':False,'state':'StartTranscription'})
                    await fay_asr.send_json({'url':str(SAMPLE.resolve())})
                    result=await fay_asr.receive_str(timeout=25)
                    assert '展厅' in result
                report['native_fay_asr_protocol']=True
                silence=io.BytesIO();sf.write(silence,np.zeros(16000,np.float32),16000,format='WAV',subtype='PCM_16')
                async with http.post(BASE+'/api/asr',data=silence.getvalue(),headers=headers) as response:
                    assert response.status==200;assert (await response.json())['empty'] is True
                async with http.post(BASE+'/api/asr',data=b'not a recording'*30,headers=headers) as response:
                    assert response.status==400
                report['silence_and_invalid_audio_handled']=True
                old={j['job_id'] for j in (await health())['jobs']}
                await post('action',{'action':'welcome-wave'})
                started=time.time();await post('chat',{'text':recognized['text']})
                deadline=time.monotonic()+75
                while True:
                    h=await health()
                    jobs=[j for j in h['jobs'] if j['job_id'] not in old]
                    errors=[e for e in events if e['event']=='error']
                    assert not errors,errors
                    if h['dialogue_verified'] and jobs and all(j['status']=='ready' for j in jobs):break
                    assert time.monotonic()<deadline,(h.get('speech'),jobs)
                    await asyncio.sleep(.25)
                assert counts['voiced']>10 and counts['video']>20,counts
                speech_files=list((ROOT.parent/'fay-ue4/runtime/fay-local/app/samples').glob('bailian-*.wav'))
                fresh=[p for p in speech_files if p.stat().st_mtime>=started]
                assert fresh,'Fay did not produce Bailian speech files'
                report['conversation']={'provider':h['provider']['model'],'tts':h['speech'],
                    'answer':''.join(e.get('text','') for e in events if e['event']=='answer'),
                    'audio_jobs':len(jobs),'fresh_bailian_wavs':len(fresh),'received':counts.copy(),
                    'first_audio_seconds':min(j['started_at'] for j in jobs)-started}
                print('PASS real ASR -> Fay -> Bailian TTS -> WebRTC',flush=True)
                await post('interrupt');await asyncio.sleep(.5)
                assert (await health())['audio_queue']==0
                report['interrupt_queue_empty']=True
                report['status']='REAL_LOCAL_ASR_FAY_BAILIAN_TTS_WEBRTC_PASSED'
            finally:
                await pc.close()
                for consumer in consumers:consumer.cancel()
                await asyncio.gather(*consumers,return_exceptions=True)
                reader_task.cancel();await asyncio.gather(reader_task,return_exceptions=True)
    (ROOT/'docs/voice-integration-validation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],flush=True)


if __name__=='__main__':asyncio.run(main())
