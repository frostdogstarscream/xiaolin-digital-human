"""Real Fay/Bailian -> official LiteAvatar -> decoded audiovisual artifacts."""
import asyncio
import json
import subprocess
import time
import re
from pathlib import Path

import aiohttp
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
BASE='http://127.0.0.1:8767'
FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'


async def main():
    report=dict(backend='LiteAvatar',physical_microphone_verified=False,browser_playback_verified=False,cases=[])
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=90)) as http:
        async with http.ws_connect(BASE+'/ws') as socket:
            initial=await socket.receive_json();events=[]
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':initial['client_id']}
            async def reader():
                async for msg in socket:
                    if msg.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(msg.data))
            reading=asyncio.create_task(reader())
            async def post(route,data=None):
                async with http.post(BASE+'/api/'+route,json=data or {},headers=headers) as r:
                    text=await r.text();assert r.status==200,(route,r.status,text);return json.loads(text)
            async def health():
                async with http.get(BASE+'/api/health') as r:return await r.json()
            try:
                h=await health();assert h['backend']=='LiteAvatar' and h['model_state']=='ready',h
                await post('start');await post('claim')
                sample=WORKSPACE/'fay-ue4/runtime/fay-local/app/samples/bailian-4d5c8233594740b285bb34d25bda1c98.wav'
                async with http.post(BASE+'/api/asr',data=sample.read_bytes(),headers=headers) as r:
                    assert r.status==200;asr=await r.json();assert '展厅' in asr['text'];report['asr']=asr
                assert (await post('voice-input',{'text':'请介绍自己'}))['status']=='waiting'
                report['unwoken_question_blocked']=True
                for route,payload in [('voice-input',{'text':'小霖小霖'}),('chat',{'text':'请只用十个字介绍你的能力。'})]:
                    events.clear();started=time.monotonic();decision=await post(route,payload)
                    if route=='voice-input':assert decision['status']=='waking'
                    deadline=time.monotonic()+80
                    while True:
                        jobs=[e for e in events if e['event']=='ready']
                        errors=[e for e in events if e['event']=='error'];assert not errors,errors
                        expected=decision.get('welcome','') if route=='voice-input' else next((e['text'] for e in events if e['event']=='answer_complete'),'')
                        normalize=lambda s:''.join(re.findall(r'[A-Za-z0-9\u3400-\u9fff]+',s)).lower()
                        if expected and normalize(expected) in normalize(''.join(j['text'] for j in jobs)):break
                        assert time.monotonic()<deadline,(route,events[-3:]);await asyncio.sleep(.2)
                    ready_seconds=time.monotonic()-started
                    decoded=[]
                    for job in jobs:
                        async with http.get(BASE+job['video']) as r:
                            assert r.status==200;target=ROOT/'outputs'/('integration-'+job['job_id']+'.mp4');target.write_bytes(await r.read())
                        audio=subprocess.run([str(FFMPEG),'-v','error','-i',str(target),'-f','s16le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True).stdout
                        pcm=np.frombuffer(audio,dtype='<i2').astype(float);assert np.max(np.abs(pcm))>500
                        capture=cv2.VideoCapture(str(target));frames=capture.get(cv2.CAP_PROP_FRAME_COUNT);capture.release();assert frames>10
                        assert job['report']['backend']=='LiteAvatar'
                        await socket.send_json({'event':'playback_started','job_id':job['job_id']})
                        await socket.send_json({'event':'playback_ended','job_id':job['job_id']})
                        decoded.append({'text':job['text'],'frames':frames,'audio_seconds':len(pcm)/16000,'render':job['report']})
                    if route=='voice-input':
                        deadline=time.monotonic()+4
                        while (await post('voice-state'))['busy']:
                            assert time.monotonic()<deadline;await asyncio.sleep(.1)
                        assert (await post('voice-state'))['awake']
                    report['cases'].append({'route':route,'ready_seconds':ready_seconds,'artifacts':decoded})
                    print('PASS',route,'real Fay audio -> LiteAvatar audiovisual artifact',flush=True)
                await post('voice-sleep');assert not (await post('voice-state'))['awake']
                assert not (await post('voice-state'))['busy'];report['interrupt_and_sleep']=True
                report['status']='REAL_FAY_LITEAVATAR_AUDIOVIDEO_PASSED'
            finally:reading.cancel();await asyncio.gather(reading,return_exceptions=True)
    path=ROOT/'docs/integration-validation.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(report['status'],flush=True)


if __name__=='__main__':asyncio.run(main())
