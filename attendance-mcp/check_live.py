"""Formal existing RTC: text -> MCP -> speech, ASR -> wake -> MCP, offline and recovery."""
import argparse
import asyncio
import json
import time
from pathlib import Path
import aiohttp

ROOT=Path(__file__).resolve().parent;BASE='http://127.0.0.1:8766'

def calls():
    path=ROOT/'runtime/calls.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []

async def control(script):
    proc=await asyncio.create_subprocess_exec('powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/script),
        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
    # Background Windows children can keep inherited pipe handles open after
    # PowerShell has exited. Service logs already go to owned runtime files.
    await asyncio.wait_for(proc.wait(),timeout=90)
    assert proc.returncode==0,'Service control failed: '+script

async def main(output,resume=None):
    report=dict(cases=[],physical_microphone_verified=False,physical_speaker_hearing_verified=False)
    if resume:report=json.loads((ROOT/'reports'/resume).read_text(encoding='utf-8'))
    events=[];restore=False
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=90)) as http:
        async def health():
            async with http.get(BASE+'/api/health') as r:return await r.json()
        before=await health();assert before['fay_core']
        assert before['audio_queue']==0,'Existing display is busy; no test input sent'
        session=before['sessionid'];owner=before['playback_owner'];headers={'X-Avatar-Client':'1','X-Avatar-Viewer':owner}
        async def post(path,data=None):
            async with http.post(BASE+'/api/'+path,json=data or {},headers=headers) as r:
                raw=await r.text();assert r.status==200,(path,r.status,raw);return json.loads(raw)
        async with http.ws_connect(BASE+'/ws') as ws:
            initial=await ws.receive_json();pc=None;consumers=[];received=dict(audio=0,video=0,voiced=0)
            if not before['rtc_connected']:
                from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription
                import numpy as np
                owner=initial['client_id'];headers['X-Avatar-Viewer']=owner
                pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
                @pc.on('track')
                def track_added(track):
                    async def consume():
                        try:
                            while True:
                                frame=await track.recv();received[track.kind]+=1
                                if track.kind=='audio' and np.max(np.abs(frame.to_ndarray().astype(float)))>500:received['voiced']+=1
                        except Exception:pass
                    consumers.append(asyncio.create_task(consume()))
                pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
                await pc.setLocalDescription(await pc.createOffer())
                answer=await post('offer',{'type':'offer','sdp':pc.localDescription.sdp});session=answer['sessionid']
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
                deadline=time.monotonic()+20
                while pc.connectionState!='connected':
                    assert time.monotonic()<deadline,'Temporary RTC did not connect';await asyncio.sleep(.1)
                report['temporary_rtc_receiver']=True
            async def listen():
                async for msg in ws:
                    if msg.type==aiohttp.WSMsgType.TEXT:
                        item=json.loads(msg.data);item['observed_at']=time.time();events.append(item)
            reader=asyncio.create_task(listen())
            async def case(name,route,text,expected):
                previous=next((item for item in report['cases'] if item['case']==name),None)
                if previous:return previous
                start=time.time();offset=len(events);baseline=len(calls());old={j['job_id'] for j in (await health())['jobs']}
                result=await post(route,{'text':text})
                deadline=time.monotonic()+150
                while True:
                    h=await health();local=events[offset:]
                    assert h['sessionid']==session and h['playback_owner']==owner,'Display ownership changed'
                    assert not h['render_error'];assert not [e for e in local if e['event']=='error'],local[-4:]
                    jobs=[j for j in h['jobs'] if j['job_id'] not in old]
                    complete=[e for e in local if e['event']=='answer_complete']
                    voice=await post('voice-state') if route=='voice-input' else None
                    if complete and jobs and all(j['status']=='ready' for j in jobs) and (not voice or not voice['busy']) and h['active_action']=='idle':break
                    assert time.monotonic()<deadline,('Timeout',name,jobs,local[-5:]);await asyncio.sleep(.2)
                answer=complete[-1]['text'];actual=calls()[baseline:]
                assert len(actual)==expected,(name,len(actual),answer)
                if expected:
                    assert ('成功' in answer or '完成' in answer) and ('测试' in answer or '占位' in answer),answer
                else:
                    assert any(word in answer for word in ('不可用','无法','未执行','没有执行','不能')),answer
                    assert '占位打卡测试成功' not in answer,answer
                assert '"gesture"' not in answer and '<think>' not in answer,answer
                record=dict(case=name,input=text,answer=answer,actual_server_calls=len(actual),server_events=actual,jobs=jobs,
                    first_text_seconds=round(next(e['observed_at'] for e in local if e['event']=='answer')-start,3),
                    first_playback_seconds=round(min(j['started_at'] for j in jobs)-start,3),
                    total_seconds=round(time.time()-start,3),motions=[e['action'] for e in local if e['event']=='action_started'])
                if actual:
                    dispatch=[json.loads(line) for line in (ROOT/'runtime/dispatch.jsonl').read_text(encoding='utf-8').splitlines()]
                    matching=[d for d in dispatch if d['started']>=start and d['ended']<=time.time()]
                    assert len(matching)==1,(name,'Expected one native dispatcher receipt',matching)
                    d=matching[0];record['native_receipt']=d
                    record['rpc_seconds']=round(d['ended']-d['started'],3)
                    final_event=next((e for e in local if e['event']=='answer' and e['observed_at']>=d['ended']),None)
                    record['first_final_text_seconds']=round(final_event['observed_at']-start,3) if final_event else None
                    final_jobs=[j for j in jobs if j['received_at']>=d['ended']]
                    record['first_final_playback_seconds']=round(min(j['started_at'] for j in final_jobs)-start,3)
                report['cases'].append(record)
                (ROOT/'reports'/output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:record[k] for k in ('case','answer','actual_server_calls','first_text_seconds','first_playback_seconds','total_seconds')},ensure_ascii=True),flush=True)
            try:
                await case('text','chat','请帮我完成一次上班签到测试。',1)
                fixture=json.loads((ROOT/'runtime/voice-input.json').read_text(encoding='utf-8'))
                async with http.post(BASE+'/api/asr',data=Path(fixture['path']).read_bytes(),headers=headers) as response:
                    assert response.status==200;recognized=await response.json()
                report['asr']=recognized;assert '打卡' in recognized['text'],recognized
                await post('voice-sleep')
                await case('asr_wake_question','voice-input',recognized['text'],1)
                baseline=len(calls());restore=True
                await control('Stop-AttendanceMcp.ps1')
                registration=json.loads((ROOT/'runtime/registration.json').read_text(encoding='utf-8'))
                async with http.post(f'http://127.0.0.1:5010/api/mcp/servers/{registration["server_id"]}/call',
                    json={'method':'attendance_check_in','params':{}}) as response:
                    failure=await response.json();assert not failure['success']
                report['offline_rpc_failed']=True
                await case('offline','chat','请帮我签到。',0)
                await control('Start-AttendanceMcp.ps1');restore=False
                assert len(calls())==baseline,'Reconnect executed the tool without a user request'
                report['reconnect_did_not_execute']=True
                await case('recovered','chat','现在请再次帮我完成一次上班签到测试。',1)
                h=await health()
                if pc:assert received['video']>50 and received['voiced']>10,received
                report.update(status='PASSED',existing_rtc_preserved=pc is None,received_tracks=received,model=h['provider']['model'],speech=h['speech'],
                    final_health=dict(fay_core=h['fay_core'],rtc_connected=h['rtc_connected'],audio_queue=h['audio_queue'],render_error=h['render_error']))
                (ROOT/'reports'/output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print('PASS formal text, ASR/wake, MCP failure/recovery and actual speech playback',flush=True)
            finally:
                if restore:await control('Start-AttendanceMcp.ps1')
                reader.cancel();await asyncio.gather(reader,return_exceptions=True)
                if pc:await pc.close()
                for consumer in consumers:consumer.cancel()
                await asyncio.gather(*consumers,return_exceptions=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='live-2026-11-04.json');parser.add_argument('--resume-from');args=parser.parse_args()
    if Path(args.output).name!=args.output:parser.error('Output must be a filename')
    if args.resume_from and Path(args.resume_from).name!=args.resume_from:parser.error('Resume must be a filename')
    asyncio.run(main(args.output,args.resume_from))
