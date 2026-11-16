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
    def __init__(self):self.ws=None;self.key=None
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
            self.ws=await websockets.connect(URL,**kwargs)
            created=await asyncio.wait_for(self.receive(),20)
            if created.get('type')!='session.created':raise ProviderError('Missing session.created')
            await self.send('session.update',session=dict(modalities=['text','audio'],voice=VOICE,
                instructions='你是亲切专业的中国女性讲解员小霖。用中文自然交流。默认用一到两句话简洁回答，不超过80个汉字。不要输出JSON、动作标签或内部控制信息。当前仅为实时语音体验，没有连接任何外部执行工具，没有考勤、订单、设备控制、知识库查询或长期记忆能力。严格区分说话与实际执行：涉及办理或执行操作的请求，明确告知本模式尚未接入，请用户切换原正式模式办理。只提供解释和引导，不模拟成功，不把用户说过的话当成已经执行的证据；参观打卡也只表达欢迎，不宣称已办理打卡成功。',
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
