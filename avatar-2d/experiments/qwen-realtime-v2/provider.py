"""Workspace-pinned Qwen realtime transport. Reads the existing key; never copies it."""
import asyncio, configparser, inspect, json, os, uuid
from pathlib import Path
import websockets

ROOT=Path(__file__).resolve().parents[2]
MODEL='qwen-audio-3.1-realtime-flash'
URL='wss://ws-sli5zyn7ll8uy18r.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model='+MODEL
VOICE='longanqian_v3.1'

def api_key():
    path=Path(os.environ.get('FAY_SYSTEM_CONF',str(ROOT.parent/'fay-ue4/runtime/fay-local/app/system.conf')))
    config=configparser.ConfigParser(interpolation=None);config.read(path,encoding='utf-8-sig')
    key=config.get('key','bailian_tts_api_key',fallback='').strip()
    if not key:raise RuntimeError('Existing Bailian TTS credential is not configured')
    return key

class ProviderError(RuntimeError): pass

class QwenConnection:
    def __init__(self,model=MODEL,instructions='',tools=None,coordinated=False):
        self.ws=None;self.key=None;self.model=model;self.instructions=instructions;self.tools=tools or [];self.coordinated=coordinated
    async def send(self,kind,**data):
        await self.ws.send(json.dumps(dict(type=kind,event_id='evt_'+uuid.uuid4().hex,**data),ensure_ascii=False))
    async def receive(self):
        event=json.loads(await self.ws.recv())
        if event.get('type')=='error':
            error=event.get('error',{})
            message=str(error.get('message','Provider request failed')).replace(self.key or '<unset>','[redacted]')
            raise ProviderError(str(error.get('code',error.get('type','unknown')))+': '+message[:300])
        return event
    async def connect(self):
        self.key=api_key()
        name='additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
        kwargs={name:{'Authorization':'Bearer '+self.key},'open_timeout':15,'close_timeout':3,'max_size':8*1024*1024}
        try:
            self.ws=await websockets.connect(URL.rsplit('=',1)[0]+'='+self.model,**kwargs)
            created=await asyncio.wait_for(self.receive(),20)
            if created.get('type')!='session.created':raise ProviderError('Missing session.created')
            await self.send('session.update',session=dict(modalities=['text','audio'],voice=VOICE,
                instructions=self.instructions,tools=self.tools,
                input_audio_format='pcm',output_audio_format='pcm',
                turn_detection=dict(type='server_vad',threshold=.5,silence_duration_ms=500)))
            while True:
                event=await asyncio.wait_for(self.receive(),20)
                if event.get('type')=='session.updated':return event['session']
        except Exception:
            await self.close();raise
    async def close(self):
        if self.ws:await self.ws.close();self.ws=None
        self.key=None
