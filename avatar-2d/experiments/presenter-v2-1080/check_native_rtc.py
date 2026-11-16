"""Actual local WebRTC delivery with frozen PCM: five clips, idle wrap and interrupt."""
import asyncio,json,time,sys
from pathlib import Path
import live_engine_v2 as engine
import numpy as np,soundfile as sf,cv2
from aiortc import RTCPeerConnection,RTCConfiguration,RTCRtpSender
from server.webrtc import HumanPlayer
from aiortc.codecs import h264
from video_encoder import configure
BACKEND=configure()
from aioice import ice
ice.get_host_addresses=lambda use_ipv4,use_ipv6:['127.0.0.1']
ROOT=engine.ROOT;OUT=ROOT/'outputs/presenter-v2-1080';OUT.mkdir(exist_ok=True)
async def main():
    report={'status':'RUNNING','scope':'local GPU and loopback WebRTC, not T4 cloud acceptance','cloud_calls':0,'cases':[],'requested_encoder':BACKEND}
    server=RTCPeerConnection(RTCConfiguration(iceServers=[]));receiver=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    tasks=[];counts={'video':0,'audio':0};shapes=set();events=[];feed=None
    try:
        assets=await asyncio.to_thread(engine.Assets);p=engine.Presenter(engine.options('v2-local-test'),assets,lambda event:events.append((time.time(),event)))
        player=HumanPlayer(p);server.addTrack(player.audio);server.addTrack(player.video)
        server.getTransceivers()[1].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('video').codecs if c.name in ('H264','rtx')])
        @receiver.on('track')
        def track_added(track):
            async def consume():
                try:
                    while True:
                        frame=await track.recv();counts[track.kind]+=1
                        if track.kind=='video':
                            shapes.add((frame.width,frame.height))
                            if counts['video']==100:
                                ok,data=cv2.imencode('.jpg',frame.to_ndarray(format='bgr24'));assert ok;(OUT/'native-webrtc-frame.jpg').write_bytes(data.tobytes())
                except Exception:pass
            tasks.append(asyncio.create_task(consume()))
        receiver.addTransceiver('audio',direction='recvonly');receiver.addTransceiver('video',direction='recvonly')
        await receiver.setLocalDescription(await receiver.createOffer());await server.setRemoteDescription(receiver.localDescription)
        await server.setLocalDescription(await server.createAnswer());await receiver.setRemoteDescription(server.localDescription)
        async def wait(condition,seconds):
            deadline=time.monotonic()+seconds
            while not condition():
                if p.error:raise RuntimeError(p.error)
                if time.monotonic()>deadline:raise TimeoutError('Native RTC condition did not complete')
                await asyncio.sleep(.05)
        await wait(lambda:counts['video']>=30 and counts['audio']>=10,45)
        assert shapes=={(1080,1920)},shapes
        first=time.monotonic();render_before=p.stats['video_frames'];receive_before=counts['video'];peak_queue=0
        wave,rate=sf.read(ROOT/'assets/calibration-speech-16k-v1.wav',dtype='float32');assert rate==16000
        async def feed_audio():
            start=time.monotonic();seq=0
            while True:
                offset=seq*2560;sample=wave[(np.arange(2560)+offset)%len(wave)]
                p.enqueue_stream(sample,{'id':'frozen-rtc-v2'},start=seq==0,generation=0)
                seq+=1;await asyncio.sleep(max(0,start+seq*.16-time.monotonic()))
        feed=asyncio.create_task(feed_audio());await asyncio.sleep(5)
        for name in ['welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod']:
            before=p.stats['motion_frames'];p.request_motion(name);length=len(assets.clips[name][1])
            await wait(lambda:p.stats['motion_frames']>=before+length and not p.motion,length/25+15)
            actual=p.stats['motion_frames']-before;assert actual==length,(name,actual,length)
            report['cases'].append(dict(action=name,rendered_frames=actual));print('PASS actual RTC gesture',name,actual,flush=True)
        await wait(lambda:p.stats['idle_loops']>=1 and p.pose[0]=='idle' and p.pose[1]>=4,45)
        elapsed=time.monotonic()-first
        report.update(device=assets.device,precision=str(assets.dtype),seconds=elapsed,dimensions=list(shapes),
            render_fps=(p.stats['video_frames']-render_before)/elapsed,receive_fps=(counts['video']-receive_before)/elapsed,
            idle_loops=p.stats['idle_loops'],stats=dict(p.stats),received=dict(counts))
        feed.cancel();await asyncio.gather(feed,return_exceptions=True);feed=None
        old=p.generation;p.flush_talk();p.enqueue_stream(np.ones(320,np.float32),{},generation=old)
        assert p.asr.queue.qsize()==0 and not p.pending_audio
        report['old_generation_rejected']=True
        report['video_encoders']=[dict(codec=getattr(getattr(sender,'_RTCRtpSender__encoder',None),'codec',None).name,
            target_bitrate=getattr(sender,'_RTCRtpSender__encoder').target_bitrate) for sender in server.getSenders()
            if sender.kind=='video' and getattr(getattr(sender,'_RTCRtpSender__encoder',None),'codec',None)]
        report['status']='PASSED' if report['receive_fps']>=24.9 else 'PERFORMANCE_BELOW_TARGET'
    except Exception as error:
        import traceback;traceback.print_exc();report.update(status='FAILED',error=str(error),error_type=type(error).__name__)
    finally:
        if feed:feed.cancel();await asyncio.gather(feed,return_exceptions=True)
        (OUT/'native-rtc-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if 'player' in locals():
            quit_event=getattr(player,'_HumanPlayer__thread_quit',None)
            if quit_event:quit_event.set()
            engine.base.clear_queue(player.audio._queue);engine.base.clear_queue(player.video._queue)
            thread=getattr(player,'_HumanPlayer__thread',None)
            if thread:await asyncio.to_thread(thread.join,5)
        await server.close();await receiver.close()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        (OUT/'native-rtc-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
asyncio.run(main())
