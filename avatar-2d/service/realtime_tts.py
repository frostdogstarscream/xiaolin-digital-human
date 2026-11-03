"""Fay-thread realtime synthesis: provider PCM is forwarded before WAV completion."""
import asyncio
import base64
import json
import time
import uuid
import wave
from pathlib import Path

import requests
import websockets

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'


class RealtimeUnavailable(RuntimeError):
    """Legacy presenter has no PCM ingress; safe to use the file adapter."""


def stream_sample(text,context,value):
    try:manifest=json.loads((ROOT/'runtime/realtime-ingress.json').read_text(encoding='utf-8'))
    except FileNotFoundError:raise RealtimeUnavailable() from None
    # Destination is always this local service; the manifest only grants access.
    endpoint='http://127.0.0.1:'+str(int(manifest['port']))+'/api/tts/'
    headers={'X-Avatar-Client':'1','X-Avatar-TTS':manifest['token']}
    target=FAY/'samples'/('bailian-realtime-'+uuid.uuid4().hex+'.wav')
    with requests.Session() as local:
        local.trust_env=False
        def post(route,**kwargs):
            response=local.post(endpoint+route,headers=headers,timeout=(2,8),**kwargs)
            if route=='begin' and response.status_code==404:raise RealtimeUnavailable()
            if response.status_code!=200:raise RuntimeError('实时语音已停止或数字人连接不可用')
            return response.json()
        job=post('begin',json={**context,'text':text,'file':target.name,'model':value['realtime_model']})['job_id']
        headers['X-Avatar-TTS-Job']=job
        try:
            asyncio.run(_synthesize(text,value,target,post,headers))
            post('end',json={'ok':True})
            return str(target)
        except Exception:
            try:post('end',json={'ok':False})
            except Exception:pass
            # Keep completed files, remove only this turn's partial output.
            if target.exists():target.unlink()
            raise RuntimeError('百炼实时语音未完成，请检查网络或重新提问') from None


async def _synthesize(text,value,target,post,headers):
    options=dict(extra_headers={'Authorization':'Bearer '+value['api_key']},open_timeout=12,close_timeout=2,max_size=4*1024*1024)
    async with websockets.connect(value['realtime_url']+'?model='+value['realtime_model'],**options) as socket:
        async def send(kind,**data):await socket.send(json.dumps({'event_id':'event_'+uuid.uuid4().hex,'type':kind,**data}))
        async def receive():
            event=json.loads(await asyncio.wait_for(socket.recv(),timeout=25))
            if event.get('type')=='error':raise RuntimeError('百炼实时语音服务返回错误')
            return event
        created=await receive()
        if created.get('type')!='session.created':raise RuntimeError('实时会话未建立')
        await send('session.update',session={'mode':'commit','voice':value['voice'],'language_type':'Chinese','response_format':'pcm','sample_rate':24000})
        while (await receive()).get('type')!='session.updated':pass
        await send('input_text_buffer.append',text=text)
        await send('input_text_buffer.commit')
        total=0;sequence=0;deadline=time.monotonic()+90
        with wave.open(str(target),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
            while time.monotonic()<deadline:
                event=await receive();kind=event.get('type')
                if kind=='response.audio.delta':
                    pcm=base64.b64decode(event.get('delta',''),validate=True)
                    if not pcm or len(pcm)%2:raise RuntimeError('实时 PCM 格式错误')
                    total+=len(pcm)
                    if total>24000*2*60:raise RuntimeError('实时语音超出一分钟')
                    output.writeframesraw(pcm)
                    headers['X-Avatar-TTS-Seq']=str(sequence)
                    post('packet',data=pcm);sequence+=1
                if kind=='response.done':break
            else:raise RuntimeError('实时语音超时')
        if not total:raise RuntimeError('实时语音为空')
        await send('session.finish')
