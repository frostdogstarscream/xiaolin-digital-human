"""Exercise real loopback Fay -> offline TTS -> WebSocket -> GPU render; no cloud requests."""
import asyncio
import json
import subprocess
import time
from pathlib import Path

from aiohttp import ClientSession,ClientTimeout

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'
FFBIN=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin'
HEADERS={'X-Avatar-Client':'1'}


async def main():
    results=[]
    async with ClientSession(trust_env=False,timeout=ClientTimeout(total=100)) as client:
        async def health():
            async with client.get(BASE+'/api/health') as r:
                assert r.status==200
                return await r.json()
        async def post(path,data=None):
            async with client.post(BASE+'/api/'+path,json=data or {},headers=HEADERS) as r:
                assert r.status==200,(path,r.status,await r.text())
                return await r.json()
        deadline=time.monotonic()+60
        while True:
            h=await health()
            if h['model_state']=='ready' and h['fay_connected']:break
            assert time.monotonic()<deadline,'Model or Fay connection did not become ready'
            await asyncio.sleep(1)
        if not h['fay_core']:await post('start')
        h=await health();assert h['fay_core'],'Fay core must be running'
        async with client.post(BASE+'/api/interrupt',json={}) as r:assert r.status==403
        async with client.post(BASE+'/api/interrupt',json={},headers={**HEADERS,'Origin':'https://untrusted.invalid'}) as r:assert r.status==403
        async with client.get(BASE+'/output/invalid/../../system.conf') as r:assert r.status in (400,404)
        if not h['provider']['configured']:
            async with client.post(BASE+'/api/chat',json={'text':'测试'},headers=HEADERS) as r:assert r.status==409
        print('PASS: loopback access guards and unconfigured-model gate',flush=True)
        for text,action in [('欢迎来到展厅','welcome-wave'),('再见期待下次见','goodbye-wave'),
                            ('比如您可以查看展厅介绍','explain-open-palms'),('明白已收到','acknowledge-nod')]:
            before={j['job_id'] for j in (await health())['jobs']}
            started=time.monotonic();await post('say',{'text':text})
            deadline=time.monotonic()+75;job=None
            while True:
                jobs=[j for j in (await health())['jobs'] if j['job_id'] not in before]
                if jobs:
                    job=jobs[0]
                    assert job['action']==action,(text,job)
                    assert job['status'] not in ('error','cancelled'),job
                    if job['status']=='ready':break
                assert time.monotonic()<deadline,('Timed out',text,job)
                await asyncio.sleep(.5)
            directory=ROOT/'runtime/sessions'/job['job_id']
            video=directory/'speaking.mp4'
            subprocess.run([str(FFBIN/'ffmpeg.exe'),'-hide_banner','-v','error','-xerror','-i',str(video),
                            '-map','0:v:0','-map','0:a:0','-f','null','-'],check=True)
            probe=json.loads(subprocess.check_output([str(FFBIN/'ffprobe.exe'),'-v','error','-show_streams','-of','json',str(video)],encoding='utf-8'))
            v=next(s for s in probe['streams'] if s['codec_type']=='video')
            a=next(s for s in probe['streams'] if s['codec_type']=='audio')
            assert int(v['nb_frames'])==job['report']['frames']
            assert v['avg_frame_rate']=='25/1' and v['codec_name']=='h264'
            assert abs(float(v['duration'])-float(a['duration']))<.08
            results.append(dict(action=action,job_id=job['job_id'],fay_text=text,report=job['report'],
                                strict_decode_passed=True,end_to_end_generation_seconds=time.monotonic()-started,
                                video=str(video)))
            print('PASS:',action,job['report']['frames'],'frames',flush=True)
        before={j['job_id'] for j in (await health())['jobs']}
        await post('say',{'text':'比如我们现在测试打断功能，正在生成的语音和动作应该立即停止，并且不能在下一轮重新出现。'})
        deadline=time.monotonic()+30;cancelled=None
        while True:
            jobs=[j for j in (await health())['jobs'] if j['job_id'] not in before]
            if jobs and jobs[0]['status']=='rendering':cancelled=jobs[0]['job_id'];break
            assert time.monotonic()<deadline,'No active render to cancel'
            await asyncio.sleep(.1)
        epoch=(await post('interrupt'))['epoch']
        await asyncio.sleep(2)
        h=await health();job=next(j for j in h['jobs'] if j['job_id']==cancelled)
        assert job['status']=='cancelled'
        assert not any(e['event']=='ready' and e['job_id']==cancelled for e in h['events'])
        report=dict(status='REAL_FAY_LOCAL_SPEECH_ACTION_RENDER_TESTS_PASSED',cases=results,
                    interrupt=dict(job_id=cancelled,status=job['status'],epoch=epoch,late_ready_rejected=True),
                    loopback_guards=True,unconfigured_chat_gated=not h['provider']['configured'],
                    cloud_model_calls=0,tts_provider='Windows offline SAPI',
                    cloud_llm_verified=False,microphone_asr_verified=False,target_hardware_verified=False,
                    browser_full_playback_verified=False)
        (ROOT/'docs').mkdir(exist_ok=True)
        (ROOT/'docs/fay-integration-validation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: active rendering cancellation and no late-ready event',flush=True)
        print(report['status'],flush=True)


if __name__=='__main__':asyncio.run(main())
