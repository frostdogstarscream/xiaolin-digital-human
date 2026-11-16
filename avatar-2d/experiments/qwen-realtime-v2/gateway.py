"""Isolated audio-to-audio trial. No production Fay writes or credentials in browser."""
import asyncio,audioop,base64,hashlib,json,logging,os,re,signal,sys,time,uuid
from pathlib import Path
import numpy as np
from aiohttp import web,WSMsgType
from provider import QwenConnection,MODEL,VOICE
from capabilities import Settings,Router,COORDINATOR,instruction,credentials
from wake_gate import WakeBuffer,WAKE_WORD,WELCOME,TIMEOUT_SECONDS,wake_question,wav_bytes
import aiohttp

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
from gesture_planner import ActionController

PORT=int(os.environ.get('QWEN_DEMO_PORT','8771'))
ORIGIN=os.environ.get('QWEN_DEMO_ORIGIN',f'http://127.0.0.1:{PORT}')
ALLOWED={ORIGIN,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
OUT=engine.ROOT/'outputs/qwen-realtime-v2';OUT.mkdir(parents=True,exist_ok=True)

@web.middleware
async def origin_gate(request,handler):
    origin=request.headers.get('Origin')
    if origin and origin not in ALLOWED:raise web.HTTPForbidden(text='Origin rejected')
    if request.method not in ('GET','HEAD') and origin not in ALLOWED:raise web.HTTPForbidden()
    return await handler(request)

class Session:
    def __init__(self,gateway,ws,user):
        self.gateway=gateway;self.ws=ws;self.id=uuid.uuid4().hex;self.provider=None;self.reader=None
        self.p=None;self.player=None;self.pc=None;self.lock=asyncio.Lock();self.idle=asyncio.Event();self.idle.set()
        self.response=None;self.blocked=set();self.jobs={};self.connect_lock=asyncio.Lock();self.closed=False
        self.mic_bytes=0;self.last_input_at=None
        self.user=user;self.turn=None;self.epoch=0;self.actions=ActionController();self.background=set();self.inputs={}
        self.wake_buffer=WakeBuffer();self.wake_listening=False;self.awake=False;self.wake_epoch=0;self.wake_task=None;self.wake_activity=0.
        self.close_lock=asyncio.Lock();self.wake_pending=bytearray()
        self.model_connects=0;self.wake_checks=0;self.wake_detections=0
    def background_task(self,coroutine):
        task=asyncio.create_task(coroutine);self.background.add(task);task.add_done_callback(self.background.discard);return task
    def begin_turn(self,text='',item_id=None):
        if self.turn and not self.turn.get('completed'):self.turn['cancelled']=True
        self.epoch+=1;self.actions.begin(self.epoch)
        self.turn=dict(id=uuid.uuid4().hex,user=self.user,revision=self.gateway.settings.value['revision'],text=text,
            epoch=self.epoch,cancelled=False,coordinated=False,gesture='idle',plan_id=uuid.uuid4().hex,loops=0)
        if item_id:self.inputs[item_id]=self.turn
        if len(self.inputs)>128:
            for key in list(self.inputs)[:-64]:self.inputs.pop(key,None)
        return self.turn
    def plan_gesture(self,gesture):
        turn=self.turn
        signal={**self.actions.context(turn['epoch']),**dict(gesture=gesture,plan_id=turn['plan_id'])}
        actual=self.actions.reserve(signal,turn['epoch']);turn['gesture']=actual;return actual
    async def refresh_instruction(self):
        if self.provider:
            extra='本轮是被“小霖小霖”唤醒后的首问，只回答问题，不再额外播报欢迎词。若用户没有禁止动作，可优先选择迎宾动作，本轮仍最多一个动作。' if self.turn and self.turn.get('wake_first') else ''
            await self.provider.send('session.update',session=dict(instructions=instruction(self.gateway.settings.public(),self.actions.context(self.epoch))+extra,tools=[COORDINATOR] if self.gateway.settings.active() else []))
    async def emit(self,kind,**values):
        if not self.ws.closed:await self.ws.send_json(dict(type=kind,**values))
    async def offer(self,data):
        async with self.lock:
            if self.pc:raise web.HTTPConflict(text='Already connected')
            def callback(event):
                asyncio.run_coroutine_threadsafe(self.playback(event),self.gateway.loop)
            self.p=self.gateway.engine.Presenter(self.gateway.engine.options(self.id),self.gateway.assets,callback)
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
        if event.get('motion_start') and self.actions.started(event):
            self.gateway.router.store.audit(job['turn']['id'],'gesture_started',gesture=event['motion_start'])
            await self.emit('gesture',gesture=event['motion_start'])
        if event.get('status')=='start':
            job['first_play_at']=time.monotonic()
            await self.emit('playing',response_id=job['id'],pcm_to_play_ms=(job['first_play_at']-job['first_pcm_at'])*1000)
        if event.get('end'):
            self.wake_activity=time.monotonic()
            job['ended_at']=time.monotonic()
            await self.emit('playback_done',response_id=job['id'])
            fields={k:v for k,v in job.items() if k in ('id','first_pcm_at','created_at','first_play_at','ended_at','audio_bytes','delta_count')}
            with (OUT/'playback-metrics.jsonl').open('a') as log:log.write(json.dumps(fields)+'\n')
            turn=job['turn']
            if turn.get('welcome_only') and self.provider:await self.refresh_instruction()
            if not turn.get('cancelled'):
                turn['completed']=True;turn['answer']=job['text']
                if turn.get('text') and not turn.get('welcome_only') and not turn.get('memory_started'):
                    turn['memory_started']=True;self.background_task(self.gateway.router.remember(turn,job['text']))
    async def start(self):
        if not self.pc or self.pc.connectionState!='connected':raise RuntimeError('请等待人物音视频连接完成')
        async with self.connect_lock:
            if self.provider:return
            revision=self.gateway.settings.value['revision']
            provider=QwenConnection(model=self.gateway.settings.value['model'],
                instructions=instruction(self.gateway.settings.public(),self.actions.context(self.epoch)),
                tools=[COORDINATOR] if self.gateway.settings.active() else [],coordinated=self.gateway.settings.active())
            try:session=await provider.connect()
            except Exception as error:raise RuntimeError('实时模型连接失败：'+str(error)) from None
            if self.closed or revision!=self.gateway.settings.value['revision']:
                await provider.close();raise RuntimeError('配置已变更，旧模型连接已关闭，请重新提问。')
            self.provider=provider;self.reader=asyncio.create_task(self.receive_provider())
            self.model_connects+=1
            await self.emit('provider_ready',model=self.gateway.settings.value['model'],voice=session.get('voice'))
    def clear_local(self):
        if self.response:self.blocked.add(self.response)
        if self.p:self.p.flush_talk()
        if self.turn and not self.turn.get('completed'):self.turn['cancelled']=True
        self.actions.cancel()
        self.response=None
        for job in self.jobs.values():
            if not job.get('ended_at'):job['cancelled']=True;job['pending']=b'';job['rate_state']=None
    async def interrupt(self):
        previous=self.turn
        self.clear_local()
        if self.provider and not self.idle.is_set():
            await self.provider.send('response.cancel')
            await asyncio.wait_for(self.idle.wait(),8)
        await self.close_cancelled_calls(previous,self.provider)
        await self.emit('interrupted')
    async def close_cancelled_calls(self,turn,provider):
        if not turn or not provider or self.provider is not provider:return
        for job in list(self.jobs.values()):
            if job.get('turn') is not turn:continue
            for call in job.get('calls',[]):
                if not call.get('answered'):
                    call['answered']=True
                    try:await provider.send('conversation.item.create',item=dict(type='function_call_output',call_id=call['call_id'],
                        output=json.dumps(dict(coordinated=False,status='cancelled',message='旧轮次已取消，不要重试。外部操作若已开始可能已执行，不能据此声称成功。'))))
                    except Exception:pass
    async def close_voice_cancelled_calls(self,turn,provider):
        try:await asyncio.wait_for(self.idle.wait(),5)
        except asyncio.TimeoutError:return
        await self.close_cancelled_calls(turn,provider)
    async def text(self,value,from_wake=False):
        value=str(value).strip()
        if not 1<=len(value)<=500:raise RuntimeError('问题需为1–500字')
        self.wake_epoch+=1;self.awake=True;self.wake_activity=time.monotonic()
        if self.wake_listening:await self.emit('wake_state',state='awake',word=WAKE_WORD,listening=True)
        await self.start();await self.interrupt();self.begin_turn(value)
        if from_wake:self.turn['wake_first']=True
        await self.refresh_instruction();self.last_input_at=time.monotonic()
        await self.provider.send('conversation.item.create',item=dict(type='message',role='user',content=[dict(type='input_text',text=value)]))
        self.idle.clear()
        await self.provider.send('response.create')
    async def audio(self,raw):
        if not raw or len(raw)%2 or len(raw)>32000:raise RuntimeError('Invalid microphone PCM')
        self.mic_bytes+=len(raw)
        if self.wake_listening and not self.awake:
            if self.wake_task and not self.wake_task.done():return
            pcm=self.wake_buffer.feed(raw)
            if pcm:self.wake_task=self.background_task(self.detect_wake(pcm,self.wake_epoch))
            return
        if not self.provider:
            if self.wake_listening:
                self.wake_pending.extend(raw)
                if len(self.wake_pending)>160000:del self.wake_pending[:-160000]
                return
            raise RuntimeError('请先开启唤醒监听')
        await self.provider.send('input_audio_buffer.append',audio=base64.b64encode(raw).decode())
    async def listen(self):
        if not self.pc or self.pc.connectionState!='connected':raise RuntimeError('请等待人物音视频连接完成')
        async with self.gateway.http.get('http://127.0.0.1:8780/health',timeout=aiohttp.ClientTimeout(total=4)) as response:
            response.raise_for_status();health=await response.json()
        if health.get('state')!='ready':raise RuntimeError('服务器唤醒识别服务尚未就绪')
        self.wake_listening=True
        await self.sleep_voice()
        await self.emit('listen_ready',word=WAKE_WORD,timeout_seconds=TIMEOUT_SECONDS)
    async def sleep_voice(self):
        self.wake_epoch+=1;self.awake=False;self.wake_buffer.reset();self.wake_pending.clear();self.actions.closed=True
        await self.stop_provider()
        await self.emit('wake_state',state='waiting' if self.wake_listening else 'off',word=WAKE_WORD,listening=self.wake_listening)
    async def stop_listening(self):
        self.wake_listening=False
        await self.sleep_voice()
    async def detect_wake(self,pcm,epoch):
        try:
            self.wake_checks+=1
            await self.emit('wake_state',state='checking',word=WAKE_WORD,listening=True)
            async with self.gateway.http.post('http://127.0.0.1:8780/transcribe',data=wav_bytes(pcm),headers={'X-Avatar-ASR':'1','Content-Type':'audio/wav'},timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status();recognized=await response.json()
            if epoch!=self.wake_epoch or self.closed or not self.wake_listening:return
            question=wake_question(recognized.get('text',''))
            if question is None:
                await self.emit('wake_state',state='waiting',word=WAKE_WORD,listening=True);return
            self.wake_detections+=1
            self.awake=True;self.wake_activity=time.monotonic();self.wake_buffer.reset()
            await self.emit('wake_detected',word=WAKE_WORD,has_question=bool(question),asr_seconds=recognized.get('inference_seconds'))
            await self.start()
            if epoch!=self.wake_epoch or self.closed or not self.wake_listening:return
            if question:
                await self.emit('user_text',text=question)
                await self.text(question,from_wake=True)
            else:
                await self.interrupt();self.begin_turn();self.turn['welcome_only']=True;self.turn['coordinated']=True
                if self.gateway.settings.enabled('gestures'):self.plan_gesture('welcome-wave')
                self.idle.clear()
                await self.provider.send('session.update',session=dict(instructions='你是小霖，本次为系统内部的唤醒欢迎。只说这一句：“'+WELCOME+'”。不要调用任何工具，不补充其他内容。',tools=[]))
                await self.provider.send('conversation.item.create',item=dict(type='message',role='user',content=[dict(type='input_text',text=WAKE_WORD)]))
                await self.provider.send('response.create',response=dict(modalities=['audio','text']))
            pending=bytes(self.wake_pending);self.wake_pending.clear()
            for offset in range(0,len(pending),3200):
                await self.provider.send('input_audio_buffer.append',audio=base64.b64encode(pending[offset:offset+3200]).decode())
            await self.emit('wake_state',state='awake',word=WAKE_WORD,listening=True)
        except Exception as error:
            if epoch==self.wake_epoch and not self.closed and self.wake_listening:
                await self.sleep_voice();await self.emit('error',message='唤醒未完成，请再说一次“小霖小霖”：'+type(error).__name__)
    def enqueue(self,job,raw,end=False):
        if job.get('cancelled') or job['generation']!=self.p.generation:return
        wave=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
        turn=job['turn'];context=self.actions.context(turn['epoch'])
        metadata={**context,'id':job['id'],'plan_id':turn['plan_id'],'gesture':turn['gesture'],'action':turn['gesture'] if not turn.get('motion_enqueued') else 'idle'}
        self.p.enqueue_stream(wave,metadata,start=not job['started'],end=end,generation=job['generation'])
        if not job['started'] and turn['gesture']!='idle':turn['motion_enqueued']=True
        job['started']=True
    def finish_audio(self,job):
        if not job.get('audio_done') and not job.get('cancelled') and job.get('audio_bytes'):
            self.enqueue(job,job['pending'],end=True);job['pending']=b'';job['audio_done']=True
    async def continue_tools(self,job,provider):
        turn=job['turn']
        try:
            for call in job['calls']:
                result=await call['task']
                if not self.gateway.router.current(turn) or self.turn is not turn or self.provider is not provider:return
                await provider.send('conversation.item.create',item=dict(type='function_call_output',call_id=call['call_id'],output=json.dumps(result,ensure_ascii=False)))
                call['answered']=True
                turn['coordinated']=result.get('coordinated') is True
            if not turn['coordinated']:return
            turn['loops']+=1
            if turn['loops']>2:raise RuntimeError('本轮工具规划重复，已停止，未重复执行。')
            self.idle.clear();await provider.send('response.create',response=dict(modalities=['audio','text']))
        except Exception as error:
            if self.turn is turn:await self.emit('error',message='能力协调未完成：'+type(error).__name__);self.idle.set()
    async def coordinate_call(self,turn,args):
        if turn.get('welcome_only'):
            return dict(coordinated=True,attendance=dict(ok=False,status='not_requested',executed=False),knowledge=dict(status='not_requested',matches=[]),memory=dict(status='not_requested',matches=[]),gesture=turn['gesture'])
        await self.emit('coordinating',turn_id=turn['id'])
        result=await self.gateway.router.coordinate(turn,args,self.plan_gesture)
        if self.turn is turn and self.gateway.router.current(turn):await self.emit('capability_result',turn_id=turn['id'],result=result)
        return result
    async def receive_provider(self):
        provider=self.provider
        try:
            while True:
                event=await provider.receive();kind=event.get('type');rid=event.get('response_id')
                if kind=='input_audio_buffer.speech_started':
                    previous=self.turn;self.clear_local()
                    if previous:self.background_task(self.close_voice_cancelled_calls(previous,provider))
                    self.begin_turn(item_id=event.get('item_id'));await self.refresh_instruction()
                    self.last_input_at=time.monotonic();await self.emit('speech_started',item_id=event.get('item_id'))
                elif kind=='input_audio_buffer.speech_stopped':
                    self.wake_activity=time.monotonic()
                    self.last_input_at=time.monotonic();await self.emit('speech_stopped')
                elif kind=='conversation.item.input_audio_transcription.completed':
                    turn=self.inputs.get(event.get('item_id'),self.turn)
                    if turn:
                        turn['text']=event.get('transcript','')
                        if turn.get('completed') and not turn.get('memory_started'):
                            turn['memory_started']=True;self.background_task(self.gateway.router.remember(turn,turn.get('answer','')))
                    await self.emit('user_text',text=event.get('transcript',''),item_id=event.get('item_id'))
                elif kind=='response.created':
                    self.idle.clear();self.response=event['response']['id']
                    if not self.turn:self.begin_turn()
                    self.jobs[self.response]=dict(id=self.response,generation=self.p.generation,created_at=time.monotonic(),
                        pending=b'',rate_state=None,started=False,audio_bytes=0,delta_count=0,text='',turn=self.turn,calls=[])
                    if len(self.jobs)>128:
                        for key in list(self.jobs)[:-64]:self.jobs.pop(key,None)
                    await self.emit('response_started',response_id=self.response)
                elif kind=='response.done':
                    self.idle.set();response=event['response'];job=self.jobs.get(response.get('id'))
                    if job and response['id'] not in self.blocked:
                        if response.get('status')=='completed' and job['calls']:
                            self.background_task(self.continue_tools(job,provider));continue
                        elif response.get('status')=='completed':self.finish_audio(job)
                        elif response.get('status')=='failed':
                            self.clear_local();await self.emit('error',message='模型回复失败，请重新提问。')
                        await self.emit('response_done',response_id=response['id'],status=response.get('status'),
                            audio_seconds=job['audio_bytes']/48000,input_to_pcm_ms=(job.get('first_pcm_at',job['created_at'])-(self.last_input_at or job['created_at']))*1000)
                elif rid and rid==self.response and rid not in self.blocked:
                    job=self.jobs[rid]
                    if kind=='response.function_call_arguments.done':
                        if event.get('name')!='coordinate_turn':raise RuntimeError('模型请求了未授权工具')
                        turn=job['turn'];args=json.loads(event['arguments'])
                        if not self.gateway.router.current(turn):continue
                        if 'coordination_task' not in turn:turn['coordination_task']=self.background_task(self.coordinate_call(turn,args))
                        job['calls'].append(dict(call_id=event['call_id'],task=turn['coordination_task']))
                    elif kind=='response.audio.delta':
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
            logging.getLogger('qwen').warning('Realtime provider error: %s',str(error)[:180])
            await self.emit('error',message=str(error)[:350])
            await provider.close()
            if self.provider is provider:self.provider=None
            self.awake=False;self.wake_epoch+=1;self.wake_buffer.reset()
            await self.emit('provider_stopped',listening=self.wake_listening)
            if self.wake_listening:await self.emit('wake_state',state='waiting',word=WAKE_WORD,listening=True)
    async def stop_provider(self):
        self.clear_local();self.idle.set()
        if self.reader:
            self.reader.cancel();await asyncio.gather(self.reader,return_exceptions=True);self.reader=None
        if self.provider:await self.provider.close();self.provider=None
        await self.emit('provider_stopped',listening=self.wake_listening)
    async def close(self,code=1000):
        async with self.close_lock:
            if self.closed:return
            self.closed=True;await self.stop_listening()
            if self.player:
                event=getattr(self.player,'_HumanPlayer__thread_quit',None)
                if event:event.set()
                engine.base.clear_queue(self.player.audio._queue);engine.base.clear_queue(self.player.video._queue)
                thread=getattr(self.player,'_HumanPlayer__thread',None)
                if thread:await asyncio.to_thread(thread.join,8)
            if self.pc:await self.pc.close()
            if not self.ws.closed:await self.ws.close(code=code)
            if self.background:await asyncio.gather(*list(self.background),return_exceptions=True)

class Gateway:
    def __init__(self):self.engine=engine;self.settings_lock=asyncio.Lock();self.assets=None;self.owner=None;self.loop=None;self.settings=Settings();self.http=None;self.router=None;self.monitor=None;self.owner_lock=asyncio.Lock()
    async def startup(self,app):
        self.loop=asyncio.get_running_loop();self.engine=self.lipsync_engine(self.settings.value['lipsync_backend']);self.assets=await asyncio.to_thread(self.engine.Assets)
        self.http=aiohttp.ClientSession(trust_env=False);self.router=Router(self.settings,self.http)
        self.monitor=asyncio.create_task(self.monitor_motion())
    async def monitor_motion(self):
        previous=None
        while True:
            session=self.owner
            if session and session.p and not session.closed:
                value=(session.id,session.p.motion or 'idle')
                if value!=previous:await session.emit('gesture_state',gesture=value[1]);previous=value
                if session.wake_listening and session.awake and session.idle.is_set() and not session.p.asr.queue.qsize() and not session.p.motion:
                    if time.monotonic()-session.wake_activity>=TIMEOUT_SECONDS:
                        await session.sleep_voice()
            await asyncio.sleep(.3)
    async def shutdown(self,app):
        if self.monitor:self.monitor.cancel();await asyncio.gather(self.monitor,return_exceptions=True)
        if self.owner:await self.owner.close()
        if self.http:await self.http.close()
    def authorize(self,request):
        if not self.owner or request.headers.get('X-Demo-Session')!=self.owner.id:raise web.HTTPForbidden()
        return self.owner
    async def health(self,request):
        session=self.owner
        return web.json_response(dict(status='ready',model=self.settings.value['model'],voice=VOICE,profile='presenter-v2-1080',lipsync_backend=self.settings.value['lipsync_backend'],lipsync_decoder='original',
            provider_connected=bool(session and session.provider),rtc_connected=bool(session and session.pc and session.pc.connectionState=='connected'),
            mic_bytes=session.mic_bytes if session else 0,render_stats=session.p.stats if session and session.p else {},
            audio_queue=session.p.asr.queue.qsize() if session and session.p else 0,
            render_error=session.p.error if session and session.p else None,
            rtc_state=session.pc.connectionState if session and session.pc else 'absent',
            ice_state=session.pc.iceConnectionState if session and session.pc else 'absent',
            wake_word=WAKE_WORD,wake_listening=bool(session and session.wake_listening),voice_awake=bool(session and session.wake_listening and session.awake),
            model_connects=session.model_connects if session else 0,wake_checks=session.wake_checks if session else 0,wake_detections=session.wake_detections if session else 0,
            active_action=session.p.motion if session and session.p and session.p.motion else 'idle',
            settings=self.settings.public(),tools_enabled=self.settings.enabled('mcp'),long_term_memory_enabled=self.settings.enabled('memory'),automatic_gestures_enabled=self.settings.enabled('gestures')))
    @staticmethod
    def lipsync_engine(backend):
        import importlib
        return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'live_engine_v2')
    async def settings_api(self,request):
        if request.method=='POST':
            async with self.settings_lock:
                try:data=self.settings.validate(await request.json())
                except ValueError as error:raise web.HTTPBadRequest(text=str(error))
                changed=data['lipsync_backend']!=self.settings.value['lipsync_backend']
                next_engine=self.engine;next_assets=self.assets
                if changed:
                    next_engine=self.lipsync_engine(data['lipsync_backend'])
                    try:next_assets=await asyncio.to_thread(next_engine.Assets)
                    except Exception:
                        logging.exception('Lip-sync model load failed')
                        raise web.HTTPServiceUnavailable(text='唇动模型加载失败，原配置继续生效')
                self.settings.update(data)
                self.engine=next_engine;self.assets=next_assets
                owner=self.owner
                if owner:
                    await owner.stop_listening()
                    await owner.emit('settings_changed',settings=self.settings.public())
                    if changed:
                        await owner.close(code=4002)
                        if self.owner is owner:self.owner=None
        return web.json_response(self.settings.public())
    async def capabilities_api(self,request):
        session=self.authorize(request)
        if request.method=='POST':
            data=await request.json()
            try:ids=await self.router.add_knowledge(session.user,data.get('title'),data.get('content'))
            except Exception as error:raise web.HTTPBadRequest(text='知识入库失败：'+str(error)[:150])
            return web.json_response(dict(ids=ids))
        key=credentials()
        return web.json_response(dict(**self.router.store.summary(session.user),namespace='当前账号 / '+session.user.split(':')[-1],
            embedding_model=key.get('embedding_api_model',''),rerank_model=key.get('rerank_api_model','')))
    async def delete_knowledge(self,request):
        session=self.authorize(request);identifier=request.match_info['identifier']
        rows=self.router.store.rows('knowledge',session.user)
        if not any(row['id']==identifier for row in rows):raise web.HTTPNotFound()
        return web.json_response(dict(deleted=bool(self.router.store.delete(identifier))))
    async def rtc_config(self,request):
        return web.json_response(dict(iceServers=cloud_runtime.ice_servers() if cloud_runtime else []))
    async def offer(self,request):return web.json_response(await self.authorize(request).offer(await request.json()))
    async def socket(self,request):
        scope=request.query.get('scope','default')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}',scope):raise web.HTTPBadRequest()
        async with self.owner_lock:
            if self.owner and request.query.get('takeover')=='1' and request.headers.get('X-Xiaolin-User'):
                await self.owner.close(code=4001);self.owner=None
            if self.owner and (self.owner.closed or (self.owner.pc and self.owner.pc.connectionState=='failed')):
                await self.owner.close();self.owner=None
            if self.owner:raise web.HTTPConflict(text='实时实验已有一个展示会话')
            ws=web.WebSocketResponse(heartbeat=20,max_msg_size=512*1024);await ws.prepare(request)
            identity=request.headers.get('X-Xiaolin-User','local-admin')
            user=hashlib.sha256(identity.encode()).hexdigest()[:24]+':'+scope
            session=Session(self,ws,user);self.owner=session
        await session.emit('ready',session_id=session.id,model=self.settings.value['model'],voice=VOICE,settings=self.settings.public())
        try:
            async for message in ws:
                try:
                    if message.type==WSMsgType.BINARY:await session.audio(message.data)
                    elif message.type==WSMsgType.TEXT:
                        data=json.loads(message.data);kind=data.get('type')
                        if kind in ('start','listen'):await session.listen()
                        elif kind=='sleep':await session.sleep_voice()
                        elif kind=='text':await session.text(data.get('text',''))
                        elif kind=='interrupt':await session.interrupt()
                        elif kind=='stop':await session.stop_listening()
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
        web.get('/api/settings',gateway.settings_api),web.post('/api/settings',gateway.settings_api),
        web.get('/api/capabilities',gateway.capabilities_api),web.post('/api/knowledge',gateway.capabilities_api),web.delete('/api/knowledge/{identifier}',gateway.delete_knowledge),
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
