"""Verify native function-call -> tool result -> streaming audio, without external effects."""
import asyncio,base64,json,time,os
from pathlib import Path
from provider import QwenConnection
from capabilities import DEFAULT,COORDINATOR,instruction

async def main():
    config=dict(DEFAULT);connection=QwenConnection(instructions=instruction(config,dict(welcome_allowed=True,motion_available=True,cooldown_remaining={})),tools=[COORDINATOR],coordinated=True)
    report=dict(status='RUNNING',scope='protocol-only coordinator probe; no real MCP or retrieval invocation');calls=[];audio=0;start=time.monotonic()
    try:
        await connection.connect();await connection.send('conversation.item.create',item=dict(type='message',role='user',content=[dict(type='input_text',text='你好，请确认你听到了。')]))
        await connection.send('response.create')
        async with asyncio.timeout(30):
            while True:
                event=await connection.receive();kind=event['type']
                if kind=='response.function_call_arguments.done':calls.append(event)
                if kind=='response.done':break
        assert len(calls)==1 and calls[0]['name']=='coordinate_turn',calls
        args=json.loads(calls[0]['arguments']);report['plan']=args
        assert args['attendance']=='skip'
        await connection.send('conversation.item.create',item=dict(type='function_call_output',call_id=calls[0]['call_id'],output=json.dumps(dict(coordinated=True,attendance=dict(ok=False,status='not_requested'),knowledge=dict(status='empty',matches=[]),memory=dict(status='empty',matches=[]),gesture=args['gesture']))))
        await connection.send('response.create',response=dict(modalities=['audio','text']))
        async with asyncio.timeout(30):
            while True:
                event=await connection.receive();kind=event['type']
                if kind=='response.audio.delta':
                    report.setdefault('first_pcm_seconds',time.monotonic()-start);audio+=len(base64.b64decode(event['delta']))
                elif kind=='response.audio_transcript.done':report['answer']=event['transcript']
                elif kind=='response.function_call_arguments.done':raise RuntimeError('Unexpected repeated coordinator')
                elif kind=='response.done':break
        assert audio and report.get('answer');report.update(status='PASSED',audio_bytes=audio)
    except Exception as error:report.update(status='FAILED',error_type=type(error).__name__,error=str(error)[:300])
    finally:
        await connection.close();out=Path(os.environ.get('QWEN_PROBE_OUTPUT','/tmp/qwen-coordination-probe.json'));out.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=True),flush=True)
    return report['status']=='PASSED'
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
