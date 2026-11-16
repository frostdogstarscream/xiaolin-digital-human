"""Isolated audio-to-audio trial. No production Fay writes or credentials in browser."""
import asyncio,audioop,base64,json,logging,os,signal,sys,time,uuid
from pathlib import Path
import numpy as np
from aiohttp import web,WSMsgType
from provider import QwenConnection,MODEL,VOICE

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))
import live_engine_v2 as engine
from server.webrtc import HumanPlayer
from video_encoder import configure
configure()
sys.path.insert(0,os.environ.get('XIAOLIN_DEPLOYMENT',''))
try:
    import cloud_runtime
    cloud_runtime.configure_rtc()
except ImportError:
    if os.environ.get('XIAOLIN_TURN_HOST'):raise
    cloud_runtime=None
from server import rtc_manager
from aiortc import RTCSessionDescription,RTCRtpSender
sys.path.insert(0,str(engine.ROOT/'service'))
from rtc_compat import prepare_local_offer

PORT=int(os.environ.get('QWEN_DEMO_PORT','8770'))
ORIGIN=os.environ.get('QWEN_DEMO_ORIGIN',f'http://127.0.0.1:{PORT}')
ALLOWED={ORIGIN,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
OUT=engine.ROOT/'outputs/qwen-realtime-v1';OUT.mkdir(parents=True,exist_ok=True)

@web.middleware
async def origin_gate(request,handler):
    origin=request.headers.get('Origin')
    if origin and origin not in ALLOWED:raise web.HTTPForbidden(text='Origin rejected')
    if request.method not in ('GET','HEAD') and origin not in ALLOWED:raise web.HTTPForbidden()
    return await handler(request)

class Session:
    def __init__(self,gateway,ws):
        self.gateway=gateway;self.ws=ws;self.id=uuid.uuid4().hex;self.provider=None;self.reader=None
        self.p=None;self.player=None;self.pc=None;self.lock=asyncio.Lock();self.idle=asyncio.Event();self.idle.set()
        self.response=None;self.blocked=set();self.jobs={};self.connect_lock=asyncio.Lock();self.closed=False
        self.mic_bytes=0;self.last_input_at=None
    async def emit(self,kind,**values):
        if not self.ws.closed:await self.ws.send_json(dict(type=kind,**values))
    async def offer(self,data):
        async with self.lock:
            if self.pc:raise web.HTTPConflict(text='Already connected')
            def callback(event):
                asyncio.run_coroutine_threadsafe(self.playback(event),self.gateway.loop)
            self.p=engine.Presenter(engine.options(self.id),self.gateway.assets,callback)
            self.player=HumanPlayer(self.p);self.pc=rtc_manager.RTCPeerConnection()
            data,_=prepare_local_offer(data)
            await self.pc.setRemoteDescription(RTCSessionDescription(type='offer',sdp=data['sdp']))
            self.pc.addTrack(self.player.audio);self.pc.addTrack(self.player.video)
            self.pc.getTransceivers()[1].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('video').codecs if c.name in ('H264','rtx')])
            await self.pc.setLocalDescription(await self.pc.createAnswer())
            return dict(type='answer',sdp=self.pc.localDescription.sdp)
    async def playback(self,event):
        job=self.jobs.get(event.get('id'))
        if not job or event.get('generation')!=self.p.generation:return
        if event.get('status')=='start':
            job['first_play_at']=time.monotonic()
            await self.emit('playing',response_id=job['id'],pcm_to_play_ms=(job['first_play_at']-job['first_pcm_at'])*1000)
        if event.get('end'):
            job['ended_at']=time.monotonic()
            await self.emit('playback_done',response_id=job['id'])
            fields={k:v for k,v in job.items() if k in ('id','first_pcm_at','created_at','first_play_at','ended_at','audio_bytes','delta_count')}
            with (OUT/'playback-metrics.jsonl').open('a') as log:log.write(json.dumps(fields)+'\n')
    async def start(self):
        if not self.pc or self.pc.connectionState!='connected':raise RuntimeError('请等待人物音视频连接完成')
        async with self.connect_lock:
            if self.provider:return
            provider=QwenConnection()
            try:session=await provider.connect()
            except Exception as error:raise RuntimeError('实时模型连接失败：'+str(error)) from None
            self.provider=provider;self.reader=asyncio.create_task(self.receive_provider())
            await self.emit('provider_ready',model=MODEL,voice=session.get('voice'))
    def clear_local(self):
        if self.response:self.blocked.add(self.response)
        if self.p:self.p.flush_talk()
        self.response=None
        for job in self.jobs.values():
            if not job.get('ended_at'):job['cancelled']=True;job['pending']=b'';job['rate_state']=None
    async def interrupt(self):
        self.clear_local()
        if self.provider and not self.idle.is_set():
            await self.provider.send('response.cancel')
            await asyncio.wait_for(self.idle.wait(),8)
        await self.emit('interrupted')
    async def text(self,value):
        value=str(value).strip()
        if not 1<=len(value)<=500:raise RuntimeError('问题需为1–500字')
        await self.start();await self.interrupt();self.last_input_at=time.monotonic()
        await self.provider.send('conversation.item.create',item=dict(type='message',role='user',content=[dict(type='input_text',text=value)]))
        self.idle.clear()
        await self.provider.send('response.create')
    async def audio(self,raw):
        if not self.provider:raise RuntimeError('请先开启实时对话')
        if not raw or len(raw)%2 or len(raw)>32000:raise RuntimeError('Invalid microphone PCM')
        self.mic_bytes+=len(raw)
        await self.provider.send('input_audio_buffer.append',audio=base64.b64encode(raw).decode())
    def enqueue(self,job,raw,end=False):
        if job.get('cancelled') or job['generation']!=self.p.generation:return
        wave=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
        self.p.enqueue_stream(wave,{'id':job['id']},start=not job['started'],end=end,generation=job['generation'])
        job['started']=True
    def finish_audio(self,job):
        if not job.get('audio_done') and not job.get('cancelled') and job.get('audio_bytes'):
            self.enqueue(job,job['pending'],end=True);job['pending']=b'';job['audio_done']=True
    async def receive_provider(self):
        provider=self.provider
        try:
            while True:
                event=await provider.receive();kind=event.get('type');rid=event.get('response_id')
                if kind=='input_audio_buffer.speech_started':
                    self.clear_local();self.last_input_at=time.monotonic();await self.emit('speech_started')
                elif kind=='input_audio_buffer.speech_stopped':
                    self.last_input_at=time.monotonic();await self.emit('speech_stopped')
                elif kind=='conversation.item.input_audio_transcription.completed':
                    await self.emit('user_text',text=event.get('transcript',''))
                elif kind=='response.created':
                    self.idle.clear();self.response=event['response']['id'];self.p.flush_talk()
                    self.jobs[self.response]=dict(id=self.response,generation=self.p.generation,created_at=time.monotonic(),
                        pending=b'',rate_state=None,started=False,audio_bytes=0,delta_count=0,text='')
                    await self.emit('response_started',response_id=self.response)
                elif kind=='response.done':
                    self.idle.set();response=event['response'];job=self.jobs.get(response.get('id'))
                    if job and response['id'] not in self.blocked:
                        if response.get('status')=='completed':self.finish_audio(job)
                        elif response.get('status')=='failed':
                            self.clear_local();await self.emit('error',message='模型回复失败，请重新提问。')
                        await self.emit('response_done',response_id=response['id'],status=response.get('status'),
                            audio_seconds=job['audio_bytes']/48000,input_to_pcm_ms=(job.get('first_pcm_at',job['created_at'])-(self.last_input_at or job['created_at']))*1000)
                elif rid and rid==self.response and rid not in self.blocked:
                    job=self.jobs[rid]
                    if kind=='response.audio.delta':
                        raw=base64.b64decode(event['delta'],validate=True)
                        if len(raw)%2:raise RuntimeError('Invalid provider PCM')
                        job.setdefault('first_pcm_at',time.monotonic());job['audio_bytes']+=len(raw);job['delta_count']+=1
                        if job['audio_bytes']>48000*60 or self.p.asr.queue.qsize()>1500:raise RuntimeError('Audio buffer limit exceeded')
                        converted,job['rate_state']=audioop.ratecv(raw,2,1,24000,16000,job['rate_state']);job['pending']+=converted
                        count=max(0,(len(job['pending'])-1)//640)*640
                        if count:self.enqueue(job,job['pending'][:count]);job['pending']=job['pending'][count:]
                        await self.emit('audio_progress',response_id=rid,seconds=job['audio_bytes']/48000)
                    elif kind=='response.audio.done':self.finish_audio(job)
                    elif kind=='response.audio_transcript.delta':
                        job['text']+=event.get('delta','');await self.emit('assistant_delta',response_id=rid,text=event.get('delta',''))
                    elif kind=='response.audio_transcript.done':
                        job['text']=event.get('transcript','');await self.emit('assistant_text',response_id=rid,text=job['text'])
        except asyncio.CancelledError:pass
        except Exception as error:
            self.clear_local();self.idle.set()
            await self.emit('error',message=str(error)[:350])
            await provider.close()
            if self.provider is provider:self.provider=None
            await self.emit('provider_stopped')
    async def stop_provider(self):
        self.clear_local();self.idle.set()
        if self.reader:
            self.reader.cancel();await asyncio.gather(self.reader,return_exceptions=True);self.reader=None
        if self.provider:await self.provider.close();self.provider=None
        await self.emit('provider_stopped')
    async def close(self):
        if self.closed:return
        self.closed=True;await self.stop_provider()
        if self.player:
            event=getattr(self.player,'_HumanPlayer__thread_quit',None)
            if event:event.set()
            engine.base.clear_queue(self.player.audio._queue);engine.base.clear_queue(self.player.video._queue)
            thread=getattr(self.player,'_HumanPlayer__thread',None)
            if thread:await asyncio.to_thread(thread.join,8)
        if self.pc:await self.pc.close()
        if not self.ws.closed:await self.ws.close()

class Gateway:
    def __init__(self):self.assets=None;self.owner=None;self.loop=None
    async def startup(self,app):
        self.loop=asyncio.get_running_loop();self.assets=await asyncio.to_thread(engine.Assets)
    async def shutdown(self,app):
        if self.owner:await self.owner.close()
    def authorize(self,request):
        if not self.owner or request.headers.get('X-Demo-Session')!=self.owner.id:raise web.HTTPForbidden()
        return self.owner
    async def health(self,request):
        session=self.owner
        return web.json_response(dict(status='ready',model=MODEL,voice=VOICE,profile='presenter-v2-1080',
            provider_connected=bool(session and session.provider),rtc_connected=bool(session and session.pc and session.pc.connectionState=='connected'),
            mic_bytes=session.mic_bytes if session else 0,render_stats=session.p.stats if session and session.p else {},
            audio_queue=session.p.asr.queue.qsize() if session and session.p else 0,
            render_error=session.p.error if session and session.p else None,
            tools_enabled=False,long_term_memory_enabled=False,automatic_gestures_enabled=False))
    async def rtc_config(self,request):
        return web.json_response(dict(iceServers=cloud_runtime.ice_servers() if cloud_runtime else []))
    async def offer(self,request):return web.json_response(await self.authorize(request).offer(await request.json()))
    async def socket(self,request):
        if self.owner and not self.owner.closed:raise web.HTTPConflict(text='实时实验已有一个展示会话')
        ws=web.WebSocketResponse(heartbeat=20,max_msg_size=512*1024);await ws.prepare(request)
        session=Session(self,ws);self.owner=session
        await session.emit('ready',session_id=session.id,model=MODEL,voice=VOICE)
        try:
            async for message in ws:
                try:
                    if message.type==WSMsgType.BINARY:await session.audio(message.data)
                    elif message.type==WSMsgType.TEXT:
                        data=json.loads(message.data);kind=data.get('type')
                        if kind=='start':await session.start()
                        elif kind=='text':await session.text(data.get('text',''))
                        elif kind=='interrupt':await session.interrupt()
                        elif kind=='stop':await session.stop_provider()
                        else:raise RuntimeError('Unknown command')
                except Exception as error:await session.emit('error',message=str(error)[:350])
        finally:
            await session.close()
            if self.owner is session:self.owner=None
        return ws

async def main():
    gateway=Gateway();app=web.Application(middlewares=[origin_gate],client_max_size=512*1024)
    app.on_startup.append(gateway.startup);app.on_shutdown.append(gateway.shutdown)
    async def gone(request):raise web.HTTPGone()
    async def page(request):return web.FileResponse(HERE/'index.html')
    async def script(request):return web.FileResponse(HERE/'demo.js')
    app.add_routes([web.get('/',page),web.get('/demo.js',script),web.get('/ws',gateway.socket),
        web.get('/api/health',gateway.health),web.get('/api/rtc-config',gateway.rtc_config),web.post('/api/offer',gateway.offer),
        web.post('/api/say',gone),web.post('/api/action',gone)])
    runner=web.AppRunner(app,access_log=None);await runner.setup();await web.TCPSite(runner,'127.0.0.1',PORT).start()
    print('Qwen realtime trial ready on loopback port '+str(PORT),flush=True)
    stopped=asyncio.Event();loop=asyncio.get_running_loop()
    for kind in (signal.SIGTERM,signal.SIGINT):
        try:loop.add_signal_handler(kind,stopped.set)
        except NotImplementedError:pass
    try:await stopped.wait()
    finally:await runner.cleanup()
if __name__=='__main__':
    logging.getLogger('aioice').setLevel(logging.WARNING)
    asyncio.run(main())
