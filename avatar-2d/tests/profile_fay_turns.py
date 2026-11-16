"""Observe the deployed Fay route; retain stage times and real RTC first audio."""
import asyncio
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

import aiohttp
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'
QUESTION='请用两句话介绍你可以如何帮助参观者，总共六十个汉字左右。'


def summarize(trace):
    m=trace['marks']
    def span(end,start):return m[end]-m[start] if end in m and start in m else None
    return dict(context_and_setup_seconds=span('llm_request_start','question_enter'),
        agent_load_seconds=span('agent_ready','question_enter'),
        role_seconds=span('role_ready','agent_ready'),memory_retrieval_seconds=span('memory_ready','memory_start'),
        prestart_tools_seconds=span('prestart_ready','memory_ready'),
        profile_and_prompt_seconds=span('profile_ready','prestart_ready'),
        resources_seconds=span('resources_ready','profile_ready'),
        history_seconds=span('history_ready','resources_ready'),tools_setup_seconds=span('tools_ready','history_ready'),
        final_prompt_build_seconds=span('prompt_ready','prompt_build_start'),
        llm_first_text_seconds=span('llm_first_text','llm_request_start'),
        intent_to_decision_seconds=span('decision_available','llm_request_start'),
        model_to_reply_text_seconds=span('reply_first_text','llm_request_start'),
        first_sentence_buffer_seconds=span('first_sentence_ready','reply_first_text'),
        sentence_enqueue_seconds=span('first_sentence_enqueued','first_sentence_ready'),
        question_to_first_sentence_seconds=span('first_sentence_enqueued','question_enter'),
        model_full_stream_seconds=span('llm_stream_done','llm_request_start'))


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trials',type=int,default=3)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/fay-stage-timing-v1.json')
    args=parser.parse_args()
    if not 1<=args.trials<=3:raise ValueError('Use 1 to 3 trials')
    digest=hashlib.sha256(QUESTION.encode()).hexdigest()
    report={'question':QUESTION,'model':'qwen-plus','input':'text; physical microphone not involved',
        'same_question_sequential_trials':True,'existing_history_preserved':True,'trials':[]}
    output=args.output
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=100)) as http:
        async with http.ws_connect(BASE+'/ws') as socket:
            initial=await socket.receive_json()
            async def drain():
                async for _ in socket:pass
            reader=asyncio.create_task(drain())
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':initial['client_id']}
            async def post(route,data=None):
                async with http.post(BASE+'/api/'+route,json=data or {},headers=headers) as r:
                    body=await r.text();assert r.status==200,(route,r.status,body)
                    return json.loads(body)
            async def health():
                async with http.get(BASE+'/api/health') as r:return await r.json()
            pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));consumers=[];counts={'audio':0,'video':0}
            @pc.on('track')
            def added(track):
                async def consume():
                    try:
                        while True:await track.recv();counts[track.kind]+=1
                    except Exception:pass
                consumers.append(asyncio.create_task(consume()))
            try:
                pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer())
                answer=await post('offer',{'sdp':pc.localDescription.sdp,'type':'offer'})
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
                deadline=time.monotonic()+20
                while pc.connectionState!='connected':
                    assert time.monotonic()<deadline;await asyncio.sleep(.1)
                await post('start')
                for i in range(args.trials):
                    old={j['job_id'] for j in (await health())['jobs']};sent=time.time()
                    await post('chat',{'text':QUESTION});deadline=time.monotonic()+85
                    trace=None
                    while True:
                        h=await health()
                        assert h['playback_owner']==initial['client_id'],'Another window took over during the timing trial'
                        jobs=[j for j in h['jobs'] if j['job_id'] not in old and j.get('started_at')]
                        for path in (ROOT/'runtime/turn-timings').glob('*.json'):
                            data=json.loads(path.read_text(encoding='utf-8'))
                            if data['started_unix']>=sent-.5 and data['meta']['question_sha256']==digest:trace=data
                        if trace and 'question_done' in trace['marks'] and jobs:break
                        assert time.monotonic()<deadline,{'trace':trace,'jobs':jobs}
                        await asyncio.sleep(.2)
                    trial={'trial':i+1,'trace':trace,'seconds':summarize(trace),
                        'question_to_audio_seconds':min(j['started_at'] for j in jobs)-sent,
                        'first_sentence_to_tts_seconds':min(j['received_at'] for j in jobs)-(trace['started_unix']+trace['marks']['first_sentence_enqueued'])}
                    report['trials'].append(trial)
                    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print('TRIAL',i+1,json.dumps({'seconds':trial['seconds'],'meta':trace['meta'],
                        'question_to_audio_seconds':trial['question_to_audio_seconds']},ensure_ascii=False),flush=True)
                    # Timing ends after generation and first real audio; discard remaining speech before the next trial.
                    await post('interrupt');await asyncio.sleep(1)
                keys=report['trials'][0]['seconds']
                report['median_seconds']={k:statistics.median(t['seconds'][k] for t in report['trials']) for k in keys if all(t['seconds'][k] is not None for t in report['trials'])}
                report['status']=f'{args.trials}_REAL_FAY_STAGE_TIMING_TRIALS_COMPLETE';report['received']=counts
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(report['status'],json.dumps(report['median_seconds']),flush=True)
            finally:
                await pc.close()
                for t in consumers+[reader]:t.cancel()
                await asyncio.gather(*consumers,reader,return_exceptions=True)


if __name__=='__main__':asyncio.run(main())
