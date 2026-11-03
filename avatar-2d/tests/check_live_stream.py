"""Receive actual native WebRTC tracks and exercise real Fay audio and controls."""
import asyncio
import json
import time
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8766'


async def main():
    report = dict(backend='LiveTalking', transport='WebRTC', cases=[])
    async with aiohttp.ClientSession(trust_env=False) as http:
        ws = await http.ws_connect(BASE+'/ws')
        state = await ws.receive_json()
        async def drain_socket():
            async for _ in ws:
                pass
        socket_reader = asyncio.create_task(drain_socket())
        headers = {'X-Avatar-Client': '1', 'X-Avatar-Viewer': state['client_id']}
        async def post(path, data=None):
            async with http.post(BASE+'/api/'+path, json=data or {}, headers=headers) as r:
                raw = await r.text()
                assert r.status == 200, (path, r.status, raw)
                result = json.loads(raw)
                return result
        async def health():
            async with http.get(BASE+'/api/health') as r:
                return await r.json()
        received = dict(video=0, audio=0, voiced=0)
        tasks = []
        async def consume(track):
            try:
                while True:
                    frame = await track.recv()
                    received[track.kind] += 1
                    if track.kind == 'audio':
                        a = frame.to_ndarray().astype(float)
                        received['voiced'] += int(np.max(np.abs(a)) > 500)
            except (asyncio.CancelledError, Exception):
                pass
        async def connect():
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            @pc.on('track')
            def on_track(track):
                tasks.append(asyncio.create_task(consume(track)))
            pc.addTransceiver('audio', direction='recvonly')
            pc.addTransceiver('video', direction='recvonly')
            await pc.setLocalDescription(await pc.createOffer())
            answer = await post('offer', dict(sdp=pc.localDescription.sdp, type='offer'))
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
            deadline = time.monotonic()+20
            while pc.connectionState != 'connected':
                assert time.monotonic() < deadline, 'WebRTC did not connect'
                await asyncio.sleep(.1)
            return pc
        pc = await connect()
        try:
            deadline = time.monotonic()+15
            while received['video'] < 15:
                assert time.monotonic() < deadline, (received, await health())
                await asyncio.sleep(.2)
            async with http.post(BASE+'/api/interrupt', json={}) as r:
                assert r.status == 403
            async with http.post(BASE+'/api/interrupt', json={}, headers={**headers, 'Origin':'https://untrusted.invalid'}) as r:
                assert r.status == 403
            report['loopback_guards'] = True
            for action, text, frames in [
                ('welcome-wave', '欢迎来到展厅，很高兴为您服务。', 175),
                ('goodbye-wave', '再见，期待您的下次到来。', 175),
                ('explain-open-palms', '下面为您介绍展厅的主要服务内容。', 225),
                ('acknowledge-nod', '好的，您的要求我已经收到。', 100),
            ]:
                await post('action', {'action':action})
                before = await health()
                old = {j['job_id'] for j in before['jobs']}
                start_motion = before['render_stats']['motion_frames']
                start_speech = before['render_stats']['speech_frames']
                voiced = received['voiced']
                sent = time.time()
                await post('say', {'text':text})
                deadline = time.monotonic()+35
                job = None
                while True:
                    h = await health()
                    jobs = [j for j in h['jobs'] if j['job_id'] not in old]
                    if jobs:
                        job = jobs[0]
                        assert job['status'] not in ('error','cancelled'), job
                        if job['status'] == 'ready' and h['render_stats']['motion_frames']-start_motion >= frames:
                            break
                    assert not h['render_error'], h
                    assert time.monotonic() < deadline, (action, job, h['render_stats'])
                    await asyncio.sleep(.15)
                assert job['action'] == action, job
                assert received['voiced'] > voiced, 'WebRTC audio was silent'
                assert h['render_stats']['speech_frames'] > start_speech
                result = dict(action=action, gesture_frames=frames, speech_frames=h['render_stats']['speech_frames']-start_speech,
                              text_to_first_audio_seconds=job['started_at']-sent,
                              fay_audio_to_first_audio_seconds=job['started_at']-job['received_at'],
                              voice_seconds=job['voice_seconds'],received_non_silent_audio=True)
                report['cases'].append(result)
                print('PASS', action, json.dumps(result), flush=True)
            # An action command during speech must not cancel the speech job.
            await post('action', {'action':'idle'})
            old = {j['job_id'] for j in (await health())['jobs']}
            await post('say', {'text':'现在测试说话过程中切换动作，语音应该持续播放，讲解员可以一边介绍内容，一边挥手，再切换为点头动作。'})
            deadline = time.monotonic()+20
            while True:
                h = await health()
                jobs = [j for j in h['jobs'] if j['job_id'] not in old]
                if jobs and jobs[0].get('started_at'):
                    job = jobs[0]; break
                assert time.monotonic()<deadline
                await asyncio.sleep(.1)
            await post('action', {'action':'welcome-wave', 'play':True})
            await asyncio.sleep(.7)
            assert next(j for j in (await health())['jobs'] if j['job_id']==job['job_id'])['status']=='streaming'
            await post('action', {'action':'acknowledge-nod', 'play':True})
            await asyncio.sleep(.4)
            interrupted_at = time.time()
            await post('interrupt')
            await asyncio.sleep(.7)
            h = await health()
            assert next(j for j in h['jobs'] if j['job_id']==job['job_id'])['status']=='cancelled'
            assert h['audio_queue']==0
            speech = h['render_stats']['speech_frames']
            await asyncio.sleep(.7)
            assert (await health())['render_stats']['speech_frames']==speech
            report['interrupt'] = dict(active_job_cancelled=True, stale_audio_queue_empty=True,
                                       no_late_speech_frames=True, observed_within_seconds=time.time()-interrupted_at)
            report['motion_during_speech'] = True
            print('PASS motion during speech and interruption', flush=True)
            # One real provider call using the already configured Fay -> Bailian path.
            await post('action', {'action':'idle'})
            old = {j['job_id'] for j in (await health())['jobs']}
            await post('chat', {'text':'请用一句不超过二十个字的话介绍你自己。'})
            deadline = time.monotonic()+65
            while True:
                h = await health()
                jobs = [j for j in h['jobs'] if j['job_id'] not in old]
                if h['dialogue_verified'] and any(j['status']=='ready' for j in jobs):
                    break
                assert time.monotonic()<deadline, 'Real Bailian dialogue did not complete'
                await asyncio.sleep(.3)
            report['bailian_dialogue'] = dict(model=h['provider']['model'], real_audio_played=True,
                                            cloud_llm_calls=1)
            print('PASS real Bailian dialogue', flush=True)
            await post('interrupt')
            await pc.close()
            pc = await connect()
            before_frames = received['video']
            deadline = time.monotonic()+12
            while received['video'] < before_frames+15:
                assert time.monotonic()<deadline, 'Reconnect produced no video'
                await asyncio.sleep(.2)
            report['reconnect_received_video'] = True
            report['received'] = received.copy()
            report['final_stats'] = (await health())['render_stats']
            report['status'] = 'REAL_FAY_WEBRTC_SPEECH_ACTION_INTERRUPT_RECONNECT_PASSED'
        finally:
            await pc.close()
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await ws.close()
            await socket_reader
    (ROOT/'docs/livetalking-validation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],flush=True)


if __name__ == '__main__':
    asyncio.run(main())
