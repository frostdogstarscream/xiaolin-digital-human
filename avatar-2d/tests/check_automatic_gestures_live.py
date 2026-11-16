"""Real Q&A/wake/TTS/motions on the already connected formal RTC session."""
import asyncio
import argparse
import hashlib
import json
import time
from pathlib import Path
import aiohttp
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8766'
OUT=ROOT/'docs/automatic-gestures-live-2026-11-04.json'

async def main(output=None,resume=None):
    global OUT
    if output:OUT=ROOT/'docs'/output
    events=[];report=dict(cases=[],physical_microphone_verified=False,physical_audio_hearing_verified=False)
    if resume:report=json.loads((ROOT/'docs'/resume).read_text(encoding='utf-8'))
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=100)) as http:
        async def health():
            async with http.get(BASE+'/api/health') as r:return await r.json()
        first=await health();assert first['rtc_connected'] and first['fay_core'] and first['action_mode']=='model'
        # Re-running an interrupted test must respect the real 60s reception timeout.
        last=max((e['time'] for e in first['events'] if e['event']=='interrupted'),default=0)
        remaining=61-(time.time()-last)
        if remaining>0 and first['render_stats']['motion_frames']>0 and not report['cases']:
            print('Waiting for real reception timeout before first-welcome case',flush=True)
            await asyncio.sleep(remaining)
        owner=first['playback_owner'];session=first['sessionid'];headers={'X-Avatar-Client':'1','X-Avatar-Viewer':owner}
        async def post(path,data=None,status=200):
            async with http.post(BASE+'/api/'+path,json=data or {},headers=headers) as r:
                text=await r.text();assert r.status==status,(path,r.status,text)
                return json.loads(text) if status==200 else text
        for route in ('say','action'):await post(route,{'text':'不能播报','action':'welcome-wave','play':True},410)
        report['retired_routes_410']=True
        async with http.get(BASE+'/') as r:html=await r.text()
        assert all(term not in html for term in ('data-mode','data-motion','speech-action','直接播报'))
        report['question_only_page']=True
        async with http.ws_connect(BASE+'/ws') as ws:
            await ws.receive_json()
            async def listen():
                async for msg in ws:
                    if msg.type==aiohttp.WSMsgType.TEXT:
                        data=json.loads(msg.data);data['observed_at']=time.time();events.append(data)
            reader=asyncio.create_task(listen())
            try:
                async def case(name,route,text,gesture,frames,question=None):
                    previous=next((item for item in report['cases'] if item['case']==name),None)
                    if previous:return previous
                    before=await health();old={j['job_id'] for j in before['jobs']};offset=len(events);start=time.time()
                    result=await post(route,{'text':text});epoch=result.get('epoch')
                    deadline=time.monotonic()+170
                    while True:
                        after=await health();local=events[offset:]
                        assert after['sessionid']==session and after['playback_owner']==owner,'Existing RTC changed'
                        assert not after['render_error'],'Render error'
                        errors=[e for e in local if e['event']=='error'];assert not errors,errors
                        jobs=[j for j in after['jobs'] if j['job_id'] not in old]
                        complete=[e for e in local if e['event']=='answer_complete']
                        voice=await post('voice-state') if route=='voice-input' else None
                        done=bool(jobs and all(j['status']=='ready' and j.get('ended_at') for j in jobs))
                        done=done and (not voice['busy'] if voice is not None else bool(complete))
                        if done and after['active_action']=='idle':break
                        assert time.monotonic()<deadline,('Timeout',name,jobs,local[-4:]);await asyncio.sleep(.2)
                    motions=[e for e in local if e['event']=='action_started']
                    assert [e['action'] for e in motions]==([gesture] if gesture!='idle' else []),(name,motions,jobs)
                    assert after['render_stats']['motion_frames']-before['render_stats']['motion_frames']==frames,(name,after['render_stats'])
                    assert all('"gesture"' not in j['text'] and not any(g in j['text'] for g in ('welcome-wave','goodbye-wave','acknowledge-nod','explain-open-palms')) for j in jobs)
                    if name=='wake_and_first_question':assert len({j['turn_id'] for j in jobs})==1,'Wake and question must share the logical turn'
                    answers=''.join(e['text'] for e in complete)
                    first_answer=next((e['observed_at']-start for e in local if e['event']=='answer'),None)
                    traces=[];query=question.rstrip(' \t\r\n，,。.!！?？、：:') if question is not None else text
                    digest=hashlib.sha256(query.encode()).hexdigest()
                    for path in (ROOT/'runtime/turn-timings').glob('*.json'):
                        trace=json.loads(path.read_text(encoding='utf-8'))
                        if trace['started_unix']>=start-.1 and trace['meta']['question_sha256']==digest:traces.append(trace)
                    if route=='chat' or question:
                        assert len(traces)==1,(name,'Expected one question trace',len(traces))
                        assert traces[0]['meta']['independent_gesture_requests']==0
                    item=dict(case=name,question=text,answer=answers,action=gesture,motion_frames=frames,
                        first_answer_seconds=round(first_answer,3) if first_answer is not None else None,
                        first_playback_seconds=round(min(j['started_at'] for j in jobs)-start,3),
                        total_seconds=round(time.time()-start,3),jobs=jobs,motions=motions,traces=traces,
                        speech_frames=after['render_stats']['speech_frames']-before['render_stats']['speech_frames'])
                    report['cases'].append(item);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps({k:item[k] for k in ('case','action','motion_frames','first_answer_seconds','first_playback_seconds','total_seconds')},ensure_ascii=True),flush=True)
                    return item

                question='请用一句话介绍你自己，不要做动作。'
                await case('wake_and_first_question','voice-input','小霖小霖，'+question,'welcome-wave',175,question=question)
                cached=await case('repeat_wake_cached_welcome','voice-input','小霖小霖','idle',0)
                assert all(j.get('transport') is None for j in cached['jobs']),'Expected reused fixed welcome audio'
                await case('confirmation','chat','我已经了解了，请确认收到，不用展开解释。','acknowledge-nod',100)
                await case('explanation','chat','请分三点详细说明数字讲解员如何帮助展厅接待，每一点解释具体用途。','explain-open-palms',225)
                await case('farewell','chat','今天先聊到这里，我要离开了，再见。','goodbye-wave',175)
                await case('quoted_goodbye','chat','“再见”是什么意思？只用一句话解释，不要做动作。','idle',0)

                # Cancel after genuine PCM playback, then reject the previous epoch's result.
                await post('chat',{'text':'请分五点介绍自然语言处理的发展，稍微详细一点。'})
                limit=time.monotonic()+80;offset=len(events)
                while not any(e['event']=='playback_started' for e in events[offset:]):
                    assert time.monotonic()<limit,'No playback to interrupt';await asyncio.sleep(.1)
                interrupted=(await post('interrupt'))['epoch'];after=await health();count=after['render_stats']['motion_frames']
                await asyncio.sleep(.6);after=await health()
                assert after['audio_queue']==0 and after['active_action']=='idle'
                assert not any(j['epoch']<interrupted and j['status'] in ('streaming','preparing') for j in after['jobs'])
                assert after['render_stats']['motion_frames']==count
                # A new input arriving while an old question prepares context
                # must retain its own native conversation and receive only its answer.
                old_turn=await post('chat',{'text':'请详细介绍自然语言处理的发展历史，至少五个要点。'})
                await asyncio.sleep(.05)
                offset=len(events)
                new_turn=await post('chat',{'text':'不要做动作，只回答：新轮次已生效。'})
                limit=time.monotonic()+80
                while True:
                    after=await health();local=events[offset:]
                    complete=next((e for e in local if e['event']=='answer_complete' and e['epoch']==new_turn['epoch']),None)
                    current_jobs=[j for j in after['jobs'] if j['epoch']==new_turn['epoch']]
                    assert not any(e['event']=='error' and e['epoch']==new_turn['epoch'] for e in local),local[-4:]
                    if complete and current_jobs and all(j['status']=='ready' for j in current_jobs):break
                    assert time.monotonic()<limit,'New input failed after a quick interruption';await asyncio.sleep(.15)
                assert '新轮次已生效' in complete['text'],complete
                assert all('自然语言处理' not in j['text'] and j['action']=='idle' for j in current_jobs)
                report['rapid_new_input']={'old_epoch':old_turn['epoch'],'new_epoch':new_turn['epoch'],
                    'answer':complete['text'],'old_result_discarded':True,'new_jobs':current_jobs}
                report.update(status='PASSED',existing_display_preserved=True,interrupt_cleared_audio_and_motion=True,
                    model=after['provider']['model'],tts=after['speech'],backend=after['backend'],action_mode=after['action_mode'])
                fixture=ROOT/'runtime/wake-sample.json'
                if fixture.is_file():
                    sample=Path(json.loads(fixture.read_text(encoding='utf-8'))['path'])
                    async with http.post(BASE+'/api/asr',data=sample.read_bytes(),headers=headers) as response:
                        assert response.status==200;recognized=await response.json()
                    report['local_asr_fixture']=recognized
                OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('PASS full live action and interruption suite',flush=True)
            finally:
                reader.cancel();await asyncio.gather(reader,return_exceptions=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--resume-from');args=parser.parse_args()
    if args.output and (Path(args.output).name!=args.output or not args.output.endswith('.json')):parser.error('Output must be a JSON filename')
    if args.resume_from and (Path(args.resume_from).name!=args.resume_from or not args.resume_from.endswith('.json')):parser.error('Resume must be a JSON filename')
    asyncio.run(main(args.output,args.resume_from))
