import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'presenter-v2-1080'))
"""Isolated T4 acceptance: native 1080p WebRTC, fixed PCM, no Fay/cloud API calls."""
import asyncio, hashlib, json, os, platform, subprocess, time
from pathlib import Path
import live_engine_v2 as engine
import numpy as np
import cv2
import psutil
import soundfile as sf
import torch
from aiortc import RTCPeerConnection, RTCConfiguration, RTCRtpSender
from aioice import ice
from server.webrtc import HumanPlayer
from video_encoder import configure

ENCODER = configure()
ice.get_host_addresses = lambda use_ipv4, use_ipv6: ['127.0.0.1']
ROOT = engine.ROOT
OUT = Path(os.environ.get('XIAOLIN_EVAL_OUTPUT', str(ROOT/'outputs/presenter-v2-1080/t4-sustained')))
DURATION = float(os.environ.get('XIAOLIN_EVAL_SECONDS', '300'))
OUT.mkdir(parents=True, exist_ok=True)

def write_json(name, value):
    temporary = OUT/(name+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(OUT/name)

def queued_audio(p, player, speech_only=False):
    def size(q, predicate):
        with q.mutex:
            return sum(1 for item in q.queue if predicate(item))
    if speech_only:
        incoming = size(p.asr.queue, lambda item: item.type == 0)
        outgoing = size(p.asr.output_queue, lambda item: item.type == 0)
        ready = size(player.audio._queue, lambda item: bool(item[1].get('id')) if item[1] else False)
    else:
        incoming = p.asr.queue.qsize(); outgoing = p.asr.output_queue.qsize()
        ready = player.audio._queue.qsize()
    with p.lock:
        pending = len(p.pending_audio)
    return dict(input_seconds=(incoming+pending)*.02,
                feature_output_seconds=outgoing*.02, audio_output_seconds=ready*.02,
                total_seconds=(incoming+pending+outgoing+ready)*.02,
                video_queue=player.video._queue.qsize())

async def main():
    started = time.monotonic()
    report = dict(status='RUNNING', scope='T4 server-local native WebRTC; not external browser/network acceptance',
                  cloud_calls=0, output_resolution=[1080,1920], requested_seconds=DURATION,
                  encoder=ENCODER, precision='FP32', batch_size=4,
                  started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), cases=[])
    tasks=[]; feed=None; resource_task=None; player=None; p=None; peers=[]
    samples=[]; resources=[]; callbacks={}; connections=[]; active_trial=None
    frames={'video':0,'audio':0}; dimensions=set(); receiver_errors=[]; receiver_events=[]; closing_peers=set()
    first_mouth={}; first_nonzero={}; first_play={}; submission={}; action_records=[]
    try:
        load_start=time.monotonic()
        assets=await asyncio.to_thread(engine.Assets)
        assert assets.device=='cuda' and assets.dtype==torch.float32, (assets.device,assets.dtype)
        assert 'T4' in torch.cuda.get_device_name(0)
        report.update(model_load_and_warmup_seconds=time.monotonic()-load_start,
                      gpu_name=torch.cuda.get_device_name(0),visible_gpu_count=torch.cuda.device_count(),
                      gpu_uuid=os.environ.get('XIAOLIN_EVAL_GPU_UUID'),
                      torch=torch.__version__, python=platform.python_version())
        assert torch.cuda.device_count()==1, 'Only reserved T4 may be visible'
        torch.cuda.reset_peak_memory_stats()
        def callback(event):
            now=time.monotonic(); identifier=event.get('id')
            if event.get('status')=='start' and identifier:
                first_play.setdefault(identifier, now)
            if event.get('end') and identifier:
                callbacks[identifier]=now
        p=engine.Presenter(engine.options('t4-isolated-1080p'),assets,callback)
        original_compose=p._compose
        def compose(token,prediction):
            result=original_compose(token,prediction)
            if prediction is not None and p.speaking and active_trial:
                first_mouth.setdefault(active_trial,time.monotonic())
            return result
        p._compose=compose

        async def wait(condition,seconds,label):
            limit=time.monotonic()+seconds
            while not condition():
                if p.error: raise RuntimeError('Render error: '+str(p.error))
                if time.monotonic()>limit: raise TimeoutError(label)
                await asyncio.sleep(.02)

        async def connect():
            server=RTCPeerConnection(RTCConfiguration(iceServers=[]))
            receiver=RTCPeerConnection(RTCConfiguration(iceServers=[]))
            peers.extend([server,receiver]); server.addTrack(player.audio); server.addTrack(player.video)
            server.getTransceivers()[1].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('video').codecs if c.name in ('H264','rtx')])
            @receiver.on('track')
            def track_added(track):
                async def consume():
                    try:
                        while True:
                            frame=await track.recv();frames[track.kind]+=1
                            if track.kind=='video':
                                dimensions.add((frame.width,frame.height))
                                if active_trial=='latency-0' and time.monotonic()-submission.get(active_trial,time.monotonic())>.8 and not (OUT/'received-speaking-frame.jpg').exists():
                                    ok,encoded=cv2.imencode('.jpg',frame.to_ndarray(format='bgr24'))
                                    assert ok
                                    (OUT/'received-speaking-frame.jpg').write_bytes(encoded.tobytes())
                            elif active_trial and active_trial not in first_nonzero:
                                data=frame.to_ndarray().astype(np.float32)
                                if np.sqrt(np.mean(data*data))>80:
                                    first_nonzero[active_trial]=time.monotonic()
                    except asyncio.CancelledError:
                        pass
                    except Exception as error:
                        receiver_events.append(dict(kind=track.kind,expected_close=receiver in closing_peers,
                            elapsed=time.monotonic()-started,error_type=type(error).__name__))
                        if receiver not in closing_peers:
                            receiver_errors.append(type(error).__name__+': '+str(error))
                tasks.append(asyncio.create_task(consume()))
            receiver.addTransceiver('audio',direction='recvonly');receiver.addTransceiver('video',direction='recvonly')
            before=frames['video']; began=time.monotonic()
            await receiver.setLocalDescription(await receiver.createOffer())
            await server.setRemoteDescription(receiver.localDescription)
            await server.setLocalDescription(await server.createAnswer())
            await receiver.setRemoteDescription(server.localDescription)
            await wait(lambda:frames['video']>=before+30,45,'WebRTC media startup')
            connections.append(dict(seconds=time.monotonic()-began, state=receiver.connectionState))
            return server,receiver

        async def close_media(server,receiver):
            closing_peers.update((server,receiver))
            quit_event=getattr(player,'_HumanPlayer__thread_quit',None)
            if quit_event: quit_event.set()
            engine.base.clear_queue(player.audio._queue);engine.base.clear_queue(player.video._queue)
            thread=getattr(player,'_HumanPlayer__thread',None)
            if thread:
                await asyncio.to_thread(thread.join,8)
                assert not thread.is_alive(),'Render worker did not stop'
            await server.close();await receiver.close()

        async def sample_resources():
            process=psutil.Process();process.cpu_percent()
            while True:
                memory=psutil.virtual_memory()
                row=dict(elapsed=time.monotonic()-started,rss_bytes=process.memory_info().rss,
                         host_used_bytes=memory.used,host_available_bytes=memory.available,cpu_percent=process.cpu_percent(),
                         gpu_allocated_bytes=torch.cuda.memory_allocated(),gpu_reserved_bytes=torch.cuda.memory_reserved())
                try:
                    command=['nvidia-smi','--query-gpu=uuid,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits']
                    result=await asyncio.to_thread(subprocess.run,command,capture_output=True,text=True,timeout=5)
                    row['nvidia_smi']=result.stdout.strip()
                except Exception as error: row['resource_error']=str(error)
                resources.append(row)
                await asyncio.sleep(1)
        resource_task=asyncio.create_task(sample_resources())
        player=HumanPlayer(p)
        server,receiver=await connect()
        wave,rate=sf.read(ROOT/'assets/calibration-speech-16k-v1.wav',dtype='float32');assert rate==16000
        report['fixture_sha256']=hashlib.sha256((ROOT/'assets/calibration-speech-16k-v1.wav').read_bytes()).hexdigest()
        async def send_for(identifier,seconds):
            total=int(seconds*rate)//2560
            began=time.monotonic();submission[identifier]=began
            for seq in range(total):
                chunk=wave[(np.arange(2560)+seq*2560)%len(wave)]
                p.enqueue_stream(chunk,{'id':identifier},start=seq==0,end=seq==total-1,generation=p.generation)
                await asyncio.sleep(max(0,began+(seq+1)*.16-time.monotonic()))

        # Independent short trials separate PCM arrival, generated mouth and playback callback.
        latency=[]
        for index in range(5):
            identifier='latency-'+str(index);p.flush_talk();active_trial=identifier
            await send_for(identifier,1.6)
            await wait(lambda:identifier in callbacks,8,'Short PCM end callback')
            assert identifier in first_mouth and identifier in first_play
            latency.append(dict(id=identifier,first_generated_mouth_ms=(first_mouth[identifier]-submission[identifier])*1000,
                first_play_callback_ms=(first_play[identifier]-submission[identifier])*1000,
                first_nonzero_received_audio_ms=(first_nonzero.get(identifier,submission[identifier])-submission[identifier])*1000
                    if identifier in first_nonzero else None))
            active_trial=None;await asyncio.sleep(.6)
        report['latency_trials']=latency
        report['latency_summary']={key:dict(median=float(np.median([row[key] for row in latency])),
            p95=float(np.percentile([row[key] for row in latency],95)))
            for key in ('first_generated_mouth_ms','first_play_callback_ms')}

        # Five minutes of real-time paced PCM without resetting queues or renderer.
        active_trial='sustained';begin=time.monotonic();before_render=p.stats['video_frames'];before_receive=frames['video']
        feed=asyncio.create_task(send_for('sustained',DURATION))
        plans=[(5,'welcome-wave'),(20,'goodbye-wave'),(35,'explain-open-palms'),(50,'acknowledge-nod')]
        pending_action=None;next_sample=begin;action_index=0
        while not feed.done():
            now=time.monotonic();elapsed=now-begin
            if action_index<len(plans) and elapsed>=plans[action_index][0]:
                name=plans[action_index][1];p.request_motion(name)
                pending_action=dict(action=name,before=p.stats['motion_frames'],started_seconds=elapsed,expected=len(assets.clips[name][1]))
                action_index+=1
            if pending_action and p.stats['motion_frames']>=pending_action['before']+pending_action['expected'] and not p.motion:
                pending_action['actual']=p.stats['motion_frames']-pending_action['before']
                assert pending_action['actual']==pending_action['expected']
                action_records.append(pending_action);pending_action=None
            if now>=next_sample:
                sample=dict(seconds=elapsed,rendered=p.stats['video_frames']-before_render,received=frames['video']-before_receive,
                            speech_frames=p.stats['speech_frames'],idle_loops=p.stats['idle_loops'],**queued_audio(p,player))
                samples.append(sample);write_json('progress.json',dict(status='RUNNING',latest=sample,actions=action_records))
                with (OUT/'samples.jsonl').open('a') as log:log.write(json.dumps(sample)+'\n')
                if len(samples)%15==0:print(json.dumps(sample),flush=True)
                next_sample+=1
            if p.error:raise RuntimeError(p.error)
            if receiver.connectionState!='connected':raise RuntimeError('WebRTC disconnected during sustained run')
            await asyncio.sleep(.02)
        await feed;feed=None
        elapsed=time.monotonic()-begin
        report.update(duration_seconds=elapsed,render_fps=(p.stats['video_frames']-before_render)/elapsed,
                      receive_fps=(frames['video']-before_receive)/elapsed,actions=action_records,
                      idle_loops=p.stats['idle_loops'],dimensions=list(dimensions),frames=dict(frames),
                      renderer_stats_before_interrupt=dict(p.stats))
        last_minute=[s for s in samples if s['seconds']>=DURATION-60]
        report['queue_last_minute']=dict(max_seconds=max(s['total_seconds'] for s in last_minute),
            median_seconds=float(np.median([s['total_seconds'] for s in last_minute])),
            slope_seconds_per_minute=float(np.polyfit([s['seconds'] for s in last_minute],[s['total_seconds'] for s in last_minute],1)[0]*60))
        for offset in range(0,int(DURATION),60):
            portion=[s for s in samples if offset<=s['seconds']<offset+60]
            if len(portion)>1:
                a,b=portion[0],portion[-1];span=b['seconds']-a['seconds']
                report['cases'].append(dict(minute=offset//60+1,render_fps=(b['rendered']-a['rendered'])/span,
                    receive_fps=(b['received']-a['received'])/span,max_queue_seconds=max(s['total_seconds'] for s in portion)))
        last_input=submission['sustained']+(int(DURATION*rate)//2560-1)*.16
        await wait(lambda:'sustained' in callbacks and queued_audio(p,player,True)['total_seconds']==0,12,'Audio drain')
        report['last_input_to_end_callback_seconds']=callbacks['sustained']-last_input
        report['input_end_to_drain_seconds']=max(0,time.monotonic()-(submission['sustained']+DURATION))

        # Interrupt ongoing gesture/PCM, reject stale generation, then deliver a new end marker.
        p.request_motion('explain-open-palms');old=p.generation
        p.enqueue_stream(np.tile(wave,2)[:32000],{'id':'interrupted'},start=True,generation=old)
        await wait(lambda:p.motion is not None,3,'Gesture start before interrupt')
        p.flush_talk();p.enqueue_stream(np.ones(320,np.float32),{'id':'stale'},generation=old)
        assert p.asr.queue.empty() and not p.pending_audio
        assert p.motion is None
        active_trial='after-interrupt';await send_for('after-interrupt',1.6)
        await wait(lambda:'after-interrupt' in callbacks,10,'Playback after interrupt')
        assert 'stale' not in first_play and 'interrupted' not in callbacks
        report['interrupt']=dict(old_generation_rejected=True,gesture_cleared=True,new_audio_completed=True)
        await close_media(server,receiver)
        # A fresh peer/player can reuse the same loaded model after disconnect.
        p=engine.Presenter(engine.options('t4-reconnect'),assets,callback)
        player=HumanPlayer(p);server,receiver=await connect()
        active_trial='after-reconnect';await send_for('after-reconnect',1.6)
        await wait(lambda:'after-reconnect' in callbacks,10,'Playback after reconnect')
        report['reconnect']=dict(media_resumed=True,audio_completed=True,connections=connections)
        report['encoder_details']=[dict(name=getattr(sender,'_RTCRtpSender__encoder').codec.name,
             target_bitrate=getattr(sender,'_RTCRtpSender__encoder').target_bitrate)
            for sender in server.getSenders() if sender.kind=='video' and getattr(sender,'_RTCRtpSender__encoder',None)]
        report['gpu_peak_allocated_bytes']=torch.cuda.max_memory_allocated()
        report['gpu_peak_reserved_bytes']=torch.cuda.max_memory_reserved()
        report['process_peak_rss_bytes']=max(r['rss_bytes'] for r in resources)
        report['host_peak_used_bytes']=max(r['host_used_bytes'] for r in resources)
        report['receiver_errors']=receiver_errors
        report['receiver_events']=receiver_events
        checks=dict(full_duration=elapsed>=DURATION-.2,render_fps=report['render_fps']>=24.9,
            receive_fps=report['receive_fps']>=24.9,queue_under_one_second=report['queue_last_minute']['max_seconds']<=1,
            queue_not_growing=report['queue_last_minute']['slope_seconds_per_minute']<=.1,
            drains_in_two_seconds=report['input_end_to_drain_seconds']<=2,
            four_complete_actions=len(action_records)==4,idle_loop=p is not None and report['idle_loops']>=1,
            exact_resolution=dimensions=={(1080,1920)},interrupt=True,reconnect=True,no_receive_errors=not receiver_errors)
        report['checks']=checks;report['status']='PASSED' if all(checks.values()) else 'ACCEPTANCE_NOT_MET'
    except Exception as error:
        import traceback
        traceback.print_exc();report.update(status='FAILED',error_type=type(error).__name__,error=str(error))
    finally:
        for task in (feed,resource_task):
            if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
        write_json('report.json',report);write_json('resources.json',resources)
        if player:
            event=getattr(player,'_HumanPlayer__thread_quit',None)
            if event:event.set()
            engine.base.clear_queue(player.audio._queue);engine.base.clear_queue(player.video._queue)
            thread=getattr(player,'_HumanPlayer__thread',None)
            if thread:await asyncio.to_thread(thread.join,8)
        closing_peers.update(peers)
        for peer in peers:
            await peer.close()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        write_json('report.json',report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return report['status']=='PASSED'

if __name__=='__main__':
    raise SystemExit(0 if asyncio.run(main()) else 1)
