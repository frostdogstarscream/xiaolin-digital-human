"""One real Go -> Fay -> Bailian streaming -> existing RTC session check."""
import asyncio
import argparse
import hashlib
import json
import time
from pathlib import Path

import aiohttp

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'
QUESTION='请用一句话回答：你叫什么名字？不要超过二十个汉字。'


async def main(output_name='opencode-go-dialogue-validation.json',allow_file_audio=False):
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=100)) as http:
        async def health():
            async with http.get(BASE+'/api/health') as response:return await response.json()
        before=await health()
        assert before['provider']['provider']=='opencode_go'
        assert before['rtc_connected'] and before['fay_core'],'An existing connected display is required'
        assert before['speech']['streaming'],'Bailian streaming must remain enabled'
        assert not any(j['status'] in ('queued','streaming','rendering','preparing') for j in before['jobs']),'Display is busy; test left it untouched'
        owner=before['playback_owner'];session=before['sessionid']
        old={j['job_id'] for j in before['jobs']}
        events=[]
        async with http.ws_connect(BASE+'/ws') as ws:
            await ws.receive_json()
            async def listen():
                async for message in ws:
                    if message.type==aiohttp.WSMsgType.TEXT:
                        data=json.loads(message.data);data['_observed_at']=time.time();events.append(data)
            reading=asyncio.create_task(listen())
            try:
                started=time.time()
                # Use the already connected display, without a new RTC offer or ownership claim.
                async with http.post(BASE+'/api/chat',headers={'X-Avatar-Client':'1','X-Avatar-Viewer':owner},
                    json={'text':QUESTION}) as response:
                    assert response.status==200,f'Chat HTTP {response.status}'
                    epoch=(await response.json())['epoch']
                deadline=time.monotonic()+95
                while True:
                    after=await health()
                    jobs=[j for j in after['jobs'] if j['job_id'] not in old and j['epoch']==epoch]
                    assert after['sessionid']==session and after['playback_owner']==owner,'Display changed during test'
                    assert not after.get('render_error'),'Renderer error'
                    error=next((e for e in events if e.get('event')=='error' and e.get('epoch')==epoch),None)
                    assert not error,'Fay returned an error event'
                    complete=next((e for e in events if e.get('event')=='answer_complete' and e.get('epoch')==epoch),None)
                    if complete and jobs and all(j['status']=='ready' and j.get('ended_at') for j in jobs):break
                    assert time.monotonic()<deadline,'Dialogue did not finish within timeout'
                    await asyncio.sleep(.15)
                streamed=[j for j in jobs if j.get('transport')=='WebSocket/PCM']
                files=[j for j in jobs if not j.get('transport')]
                if not allow_file_audio:
                    assert len(streamed)==len(jobs),'Unexpected TTS fallback or cached file audio'
                else:
                    assert len(streamed)+len(files)==len(jobs),'Unknown audio transport'
                assert all((j.get('delta_count') or 0)>0 for j in streamed),'No streamed PCM'
                frames=after['render_stats']['speech_frames']-before['render_stats']['speech_frames']
                assert frames>0,'No new speaking frames'
                first_text=min(e['_observed_at'] for e in events if e.get('event')=='answer' and e.get('epoch')==epoch)
                report=dict(status='GO_FAY_STREAMING_TTS_EXISTING_RTC_PASSED',model=after['provider']['model'],
                    collaboration_mode=after['provider'].get('collaboration',{}).get('mode','unknown'),
                    answer=complete['text'],first_answer_text_seconds=round(first_text-started,3),
                    first_playback_callback_seconds=round(min(j['started_at'] for j in jobs)-started,3),
                    tts_first_pcm_seconds=round(min(j['first_delta_at']-j['received_at'] for j in streamed),3) if streamed else None,
                    total_seconds=round(time.time()-started,3),tts_model=after['speech']['model'],
                    tts_voice=after['speech']['voice'],all_segments_streamed=len(streamed)==len(jobs),segments=len(jobs),
                    audio_path='streamed_pcm' if len(streamed)==len(jobs) else 'file_audio' if not streamed else 'mixed',
                    pcm_chunks=sum(j['delta_count'] for j in streamed),new_speaking_frames=frames,
                    existing_display_preserved=True,physical_microphone_verified=False,physical_audio_hearing_verified=False)
                report.update(question=QUESTION,request_started_unix=started,
                    first_answer_observed_unix=first_text,retained_jobs=jobs,
                    small_generation=after['provider']['collaboration'].get('small_generation'))
                digest=hashlib.sha256(QUESTION.encode()).hexdigest()
                traces=[]
                for candidate in (ROOT/'runtime/turn-timings').glob('*.json'):
                    trace=json.loads(candidate.read_text(encoding='utf-8'))
                    if trace['started_unix']>=started-.05 and trace['meta']['question_sha256']==digest:
                        traces.append(trace)
                assert len(traces)==1,'Expected one native timing trace for this question'
                trace=traces[0];m=trace['marks'];first_job=min(jobs,key=lambda j:j['started_at'])
                report['fay_trace']=trace
                report['stage_seconds']=dict(
                    entry_before_question=trace['started_unix']+m['question_enter']-started,
                    context_and_prompt=m['llm_request_start']-m['question_enter'],
                    model_to_first_content=m['llm_first_text']-m['llm_request_start'],
                    model_full_stream=m['llm_stream_done']-m['llm_request_start'],
                    first_sentence_buffer=m['first_sentence_enqueued']-m['llm_first_text'],
                    sentence_to_tts_ingress=first_job['received_at']-(trace['started_unix']+m['first_sentence_enqueued']) if first_job.get('first_delta_at') else None,
                    tts_to_first_pcm=first_job['first_delta_at']-first_job['received_at'] if first_job.get('first_delta_at') else None,
                    pcm_to_playback=first_job['started_at']-first_job['first_delta_at'] if first_job.get('first_delta_at') else None,
                    sentence_to_file_ingress=first_job['received_at']-(trace['started_unix']+m['first_sentence_enqueued']) if not first_job.get('first_delta_at') else None,
                    file_ingress_to_playback=first_job['started_at']-first_job['received_at'] if not first_job.get('first_delta_at') else None)
                path=ROOT/'docs'/output_name
                path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=True),flush=True)
                return report
            finally:
                reading.cancel();await asyncio.gather(reading,return_exceptions=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='opencode-go-dialogue-validation.json')
    parser.add_argument('--allow-file-audio',action='store_true')
    args=parser.parse_args()
    if Path(args.output).name!=args.output or not args.output.endswith('.json'):parser.error('Output must be a JSON filename')
    asyncio.run(main(args.output,allow_file_audio=args.allow_file_audio))
