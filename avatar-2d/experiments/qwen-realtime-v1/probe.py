"""One bounded, user-authorized text-to-speech round on the realtime model."""
import asyncio,base64,json,os,time,wave
from pathlib import Path
from provider import QwenConnection,MODEL,VOICE,ROOT

async def main():
    out=Path(os.environ.get('QWEN_PROBE_OUTPUT',str(ROOT/'outputs/qwen-realtime-v1/probe')));out.mkdir(parents=True,exist_ok=True)
    connection=QwenConnection();start=time.monotonic();report=dict(model=MODEL,voice=VOICE,status='RUNNING',model_calls=1)
    data=bytearray();types={}
    try:
        session=await connection.connect();report['connect_configure_seconds']=time.monotonic()-start
        report['accepted_voice']=session.get('voice')
        await connection.send('conversation.item.create',item=dict(type='message',role='user',content=[dict(type='input_text',text='请只回复：你好，我是小霖，实时语音测试成功。')]))
        submitted=time.monotonic();await connection.send('response.create')
        async with asyncio.timeout(45):
            while True:
                event=await connection.receive();kind=event.get('type');types[kind]=types.get(kind,0)+1
                if kind=='response.audio.delta':
                    report.setdefault('first_audio_seconds',time.monotonic()-submitted)
                    raw=base64.b64decode(event['delta'],validate=True);assert len(raw)%2==0;data.extend(raw)
                    if len(data)>24000*2*20:raise RuntimeError('Probe exceeded 20 audio seconds')
                elif kind=='response.audio_transcript.done':report['text']=event.get('transcript','')
                elif kind=='response.done':
                    report['response_status']=event['response'].get('status');break
        assert data and report.get('text') and report['response_status']=='completed'
        with wave.open(str(out/'response-24k.wav'),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(data)
        report.update(status='PASSED',audio_seconds=len(data)/48000,event_counts=types,total_seconds=time.monotonic()-start)
    except Exception as error:
        report.update(status='FAILED',error_type=type(error).__name__,error=str(error).replace(connection.key or '<unset>','[redacted]')[:400])
    finally:
        await connection.close();(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True),flush=True)
    return report['status']=='PASSED'
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
