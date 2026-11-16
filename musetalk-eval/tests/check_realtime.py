"""Real WebRTC receivers, sequential backends, five-minute streaming stability each."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription

ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8768'


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=300)
    parser.add_argument('--resume-candidate',action='store_true');args=parser.parse_args()
    report={'target_seconds_per_backend':args.seconds,'cloud_calls':0,'backend_order':['wav2lip','musetalk'],'results':[]}
    path=ROOT/'outputs/realtime-validation.json'
    if args.resume_candidate:
        report=json.loads(path.read_text(encoding='utf-8'))
        assert len(report['results'])>=1 and report['results'][0]['backend']=='wav2lip'
        report['results']=report['results'][:1]
        assert report['results'][0].get('reconnect') is True,'Baseline must have verified reconnection'
    headers={'X-Eval-Request':'1','X-Eval-Client':'automated-evaluation'}
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=150)) as http:
        async def get():
            async with http.get(BASE+'/api/health') as r:return await r.json()
        async def post(route,data=None):
            async with http.post(BASE+'/api/'+route,json=data or {},headers=headers) as r:
                text=await r.text();assert r.status==200,(route,r.status,text)
                return json.loads(text)
        for backend in (['musetalk'] if args.resume_candidate else report['backend_order']):
            await post('backend',{'backend':backend});deadline=time.monotonic()+150
            while True:
                h=await get();assert h['state']!='error',h
                if h['state']=='ready' and h['backend']==backend:break
                assert time.monotonic()<deadline;await asyncio.sleep(.5)
            async with http.post(BASE+'/api/play',json={},headers={'X-Eval-Request':'1'}) as r:assert r.status==409
            async with http.post(BASE+'/api/play',json={}) as r:assert r.status==403
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));consumers=[]
            received={'video':0,'audio':0,'voiced':0};arrival=[]
            playback_metrics={}
            @pc.on('track')
            def track_added(track):
                async def consume():
                    try:
                        while True:
                            frame=await track.recv();received[track.kind]+=1
                            if track.kind=='video':arrival.append(time.monotonic())
                            elif np.max(np.abs(frame.to_ndarray().astype(float)))>500:received['voiced']+=1
                    except Exception:pass
                consumers.append(asyncio.create_task(consume()))
            async def connect():
                pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer())
                answer=await post('offer',{'type':'offer','sdp':pc.localDescription.sdp})
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
                deadline=time.monotonic()+20
                while pc.connectionState!='connected':
                    assert time.monotonic()<deadline;await asyncio.sleep(.1)
            async def playback(fixture,action):
                playback_metrics.clear();playback_metrics.update(queue_max=0,gpu_peak_mb=0)
                job=await post('play',{'fixture':fixture,'action':action});deadline=time.monotonic()+65
                while True:
                    h=await get();assert not h['error'],h['error']
                    playback_metrics['queue_max']=max(playback_metrics['queue_max'],h['queue'])
                    playback_metrics['gpu_peak_mb']=max(playback_metrics['gpu_peak_mb'],h['gpu_peak_mb'])
                    j=next(x for x in h['jobs'] if x['id']==job['id'])
                    if j['status']=='ready':return j
                    assert time.monotonic()<deadline,(j,h['stats']);await asyncio.sleep(.1)
            result={'backend':backend,'model_load_seconds':h['load_seconds'],'latency_samples':[]}
            try:
                await connect()
                await playback('short','idle') # warm feature extraction and kernel shapes
                for action in ['idle','welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod']:
                    j=await playback('short',action)
                    result['latency_samples'].append({'fixture':'short','action':action,'first_video_seconds':j['first_video_at']-j['submitted_at'],
                        'first_audio_seconds':j['first_audio_at']-j['submitted_at'],'first_pose':j['first_pose']})
                    if action!='idle':assert j['first_pose']==[action,0],j
                began=time.monotonic();start_video=received['video'];start_received=len(arrival);samples=[];n=0
                while time.monotonic()-began<args.seconds:
                    action=['welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod','idle'][n%5]
                    j=await playback('long',action);h=await get()
                    samples.append({'elapsed_seconds':time.monotonic()-began,'queue':h['queue'],'fps':h['fps'],
                        'queue_peak_during_turn':playback_metrics['queue_max'],
                        'gpu_allocated_mb':h['gpu_allocated_mb'],'gpu_peak_mb':h['gpu_peak_mb']})
                    result['latency_samples'].append({'fixture':'long','action':action,'first_video_seconds':j['first_video_at']-j['submitted_at']})
                    print('STABILITY',backend,round(time.monotonic()-began,1),'fps',round(h['fps'],2),'queue',h['queue'],flush=True)
                    n+=1
                duration=time.monotonic()-began;new_arrivals=arrival[start_received:]
                fps=(len(new_arrivals)-1)/(new_arrivals[-1]-new_arrivals[0])
                video_latency=[x['first_video_seconds'] for x in result['latency_samples']]
                result.update(duration_seconds=duration,received_fps=fps,received_frames=received['video']-start_video,
                    p95_first_video_seconds=float(np.percentile(video_latency,95)),median_first_video_seconds=statistics.median(video_latency),
                    samples=samples,queue_max=max(x['queue_peak_during_turn'] for x in samples),gpu_peak_mb=max(x['gpu_peak_mb'] for x in samples),
                    sustained_25fps=fps>=24.9,queue_no_accumulation=max(x['queue_peak_during_turn'] for x in samples)<=40)
                # Interrupt a live stream, confirm queued speech/old generation disappear.
                j=await post('play',{'fixture':'long','action':'welcome-wave'});await asyncio.sleep(.6)
                before=await get();await post('action',{'action':'acknowledge-nod'});await asyncio.sleep(.2)
                assert next(x for x in (await get())['jobs'] if x['id']==j['id'])['status']=='streaming'
                await post('interrupt');await asyncio.sleep(.8);h=await get()
                assert next(x for x in h['jobs'] if x['id']==j['id'])['status']=='cancelled'
                assert h['queue']==0,h['queue'];speech=h['stats']['speech_frames'];await asyncio.sleep(.6)
                assert (await get())['stats']['speech_frames']==speech,'Stale speech frames after cancel'
                result['interrupt_and_motion_change']=True
                assert received['voiced']>10,received
                result['received']=received.copy();report['results'].append(result)
                path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                await pc.close()
                for consumer in consumers:consumer.cancel()
                await asyncio.gather(*consumers,return_exceptions=True)
            # Reconnect the same backend and receive new frames.
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));consumers=[]
            @pc.on('track')
            def reconnect_track(track):
                async def consume():
                    try:
                        while True:await track.recv();received[track.kind]+=1
                    except Exception:pass
                consumers.append(asyncio.create_task(consume()))
            try:
                old=received['video'];await connect();await asyncio.sleep(1.2)
                assert received['video']>old+10;result['reconnect']=True
            finally:
                await pc.close()
                for consumer in consumers:consumer.cancel()
                await asyncio.gather(*consumers,return_exceptions=True)
            print('BACKEND_PASS',backend,round(fps,3),result['p95_first_video_seconds'],flush=True)
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        baseline,candidate=report['results']
        report['p95_increase_seconds']=candidate['p95_first_video_seconds']-baseline['p95_first_video_seconds']
        report['latency_gate_pass']=report['p95_increase_seconds']<=.2
        report['performance_pass']=report['latency_gate_pass'] and all(x['sustained_25fps'] and x['queue_no_accumulation'] for x in report['results']) and args.seconds>=300
        report['visual_acceptance']='USER_REVIEW_REQUIRED'
        report['default_backend_changed']=False;report['status']='REAL_WEBRTC_EVALUATION_COMPLETE'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(report['status'],'performance_pass',report['performance_pass'],flush=True)


if __name__=='__main__':asyncio.run(main())
