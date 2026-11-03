"""Real Fay -> Qwen realtime PCM -> LiveTalking: first audio, cache, cancel."""
import asyncio
import json
import time
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


async def main():
    report={'physical_microphone_verified':False,'cases':[]}
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=100)) as http:
        async def health():
            async with http.get(BASE+'/api/health') as r:return await r.json()
        async with http.ws_connect(BASE+'/ws') as ws:
            initial=await ws.receive_json();events=[]
            async def read():
                async for message in ws:
                    if message.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(message.data))
            reading=asyncio.create_task(read())
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':initial['client_id']}
            async def post(path,data=None):
                async with http.post(BASE+'/api/'+path,json=data or {},headers=headers) as r:
                    text=await r.text();assert r.status==200,(path,r.status,text)
                    return json.loads(text)
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));consumers=[]
            counts={'audio':0,'video':0,'voiced':0}
            @pc.on('track')
            def track_added(track):
                async def consume():
                    try:
                        while True:
                            f=await track.recv();counts[track.kind]+=1
                            if track.kind=='audio' and np.max(np.abs(f.to_ndarray().astype(float)))>500:counts['voiced']+=1
                    except Exception:pass
                consumers.append(asyncio.create_task(consume()))
            async def wait_job(old,done=True):
                deadline=time.monotonic()+85
                while True:
                    h=await health();jobs=[j for j in h['jobs'] if j['job_id'] not in old]
                    assert not h['render_error'],h['render_error']
                    assert not any(j['status']=='error' for j in jobs),jobs
                    if jobs and all(j['status']=='ready' if done else bool(j.get('started_at')) for j in jobs):return h,jobs
                    assert time.monotonic()<deadline,{'jobs':jobs,'errors':[e for e in events if e['event']=='error']}
                    await asyncio.sleep(.1)
            try:
                pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer())
                answer=await post('offer',{'type':'offer','sdp':pc.localDescription.sdp})
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
                deadline=time.monotonic()+20
                while pc.connectionState!='connected':
                    assert time.monotonic()<deadline;await asyncio.sleep(.1)
                await post('start');h=await health();assert h['speech']['streaming'],h['speech']
                async with http.post(BASE+'/api/tts/begin',headers={'X-Avatar-Client':'1'},json={}) as r:assert r.status==403
                text='您好欢迎体验本机实时数字人的语音播报能力。此刻百炼会持续返回声音片段驱动我的口型。第一段声音开始播放时后面的内容仍然在生成。参观过程中您可以随时让我停止讲话或者配合迎宾动作。'
                old={j['job_id'] for j in h['jobs']};sent=time.time();await post('say',{'text':text})
                h,jobs=await wait_job(old)
                assert ''.join(j['text'] for j in jobs)==text,jobs
                assert all(j.get('transport')=='WebSocket/PCM' for j in jobs),jobs
                job=jobs[0];assert job['delta_count']>2,job
                assert job['started_at']<job['generation_ended_at'],job
                assert counts['voiced']>10,counts
                report['cases'].append({'type':'direct_speech','first_audio_seconds':job['started_at']-sent,
                    'tts_first_pcm_seconds':job['first_delta_at']-job['received_at'],
                    'generation_seconds':job['generation_ended_at']-job['received_at'],
                    'playback_started_before_generation_finished':True,'audio_chunks':sum(j['delta_count'] for j in jobs),
                    'voice_seconds':sum(j['voice_seconds'] for j in jobs),'segments':len(jobs)})
                print('PASS real streaming',json.dumps(report['cases'][-1]),flush=True)
                await asyncio.sleep(1.5)
                assert len([j for j in (await health())['jobs'] if j['job_id'] not in old])==len(jobs),'Duplicate file playback'
                # Same text must replay exactly once from Fay cache, rather than be suppressed.
                old={j['job_id'] for j in (await health())['jobs']};voiced=counts['voiced'];sent=time.time()
                await post('say',{'text':text});h,jobs=await wait_job(old)
                assert ''.join(j['text'] for j in jobs)==text and counts['voiced']>voiced,jobs
                assert all(j.get('transport') is None for j in jobs),jobs
                report['cases'].append({'type':'cache_replay','played_once':True,'segments':len(jobs),'first_audio_seconds':jobs[0]['started_at']-sent})
                print('PASS cache replay without duplicates',flush=True)
                old={j['job_id'] for j in h['jobs']}
                await post('say',{'text':'这是实时语音打断检查。'+text+text[:50]})
                h,jobs=await wait_job(old,done=False);job=jobs[0];await post('interrupt');await asyncio.sleep(.8)
                h=await health();assert next(j for j in h['jobs'] if j['job_id']==job['job_id'])['status']=='cancelled'
                assert h['audio_queue']==0;frames=h['render_stats']['speech_frames']
                await asyncio.sleep(.8);assert (await health())['render_stats']['speech_frames']==frames
                capability=json.loads((ROOT/'runtime/realtime-ingress.json').read_text(encoding='utf-8'))
                async with http.post(BASE+'/api/tts/packet',data=b'\0'*640,headers={'X-Avatar-Client':'1',
                        'X-Avatar-TTS':capability['token'],'X-Avatar-TTS-Job':job['job_id'],'X-Avatar-TTS-Seq':'0'}) as r:assert r.status==409
                report['interruption']={'queue_empty':True,'no_late_speech':True,'old_job_rejected':True,
                    'cancelled_during_generation':not bool(job.get('generation_ended_at'))}
                print('PASS interrupt and stale PCM rejection',flush=True)
                old={j['job_id'] for j in h['jobs']};sent=time.time();events.clear()
                await post('chat',{'text':'请用两句话介绍你可以如何帮助参观者，总共六十个汉字左右。'})
                deadline=time.monotonic()+85
                while True:
                    h=await health();jobs=[j for j in h['jobs'] if j['job_id'] not in old]
                    if jobs and all(j['status']=='ready' for j in jobs) and any(e['event']=='answer_complete' for e in events):break
                    assert time.monotonic()<deadline,{'jobs':jobs,'errors':[e for e in events if e['event']=='error']}
                    await asyncio.sleep(.2)
                assert all(j.get('transport')=='WebSocket/PCM' for j in jobs),jobs
                report['chat']={'first_audio_seconds':min(j['started_at'] for j in jobs)-sent,'segments':len(jobs),
                    'all_segments_streamed':True,'answer':next(e['text'] for e in events if e['event']=='answer_complete')}
                print('PASS Fay/Qwen dialogue with realtime TTS',json.dumps(report['chat'],ensure_ascii=False),flush=True)
                report['received']=counts.copy();report['speech']=h['speech'];report['status']='REALTIME_TTS_FAY_WEBRTC_PASSED'
                await post('interrupt')
            finally:
                await pc.close()
                for task in consumers+[reading]:task.cancel()
                await asyncio.gather(*consumers,reading,return_exceptions=True)
    (ROOT/'docs/realtime-tts-validation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],flush=True)


if __name__=='__main__':asyncio.run(main())
