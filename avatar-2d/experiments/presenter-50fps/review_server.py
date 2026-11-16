"""Isolated media experiment: fixed audio only, no LLM/TTS/memory credentials."""
from pathlib import Path
import asyncio,os,sys,time,uuid
from aiohttp import web
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
import engine50 as engine
from encoder50 import configure
configure()
sys.path.insert(0,'/app/avatar-2d/service')
import cloud_runtime
cloud_runtime.configure_rtc()
from server import rtc_manager
from server.webrtc import HumanPlayer
from aiortc import RTCSessionDescription,RTCRtpSender
import numpy as np,soundfile as sf
sys.path.insert(0,str(ROOT/'service'))
from rtc_compat import prepare_local_offer

ORIGIN='https://36.133.88.94:6444'
@web.middleware
async def gate(request,handler):
    if request.method not in ('GET','HEAD'):
        if request.headers.get('Origin')!=ORIGIN or not request.headers.get('X-Xiaolin-User'):raise web.HTTPForbidden()
    return await handler(request)

class Trial:
    def __init__(self):self.assets=None;self.pc=None;self.player=None;self.p=None;self.feed=None;self.token=None;self.lock=asyncio.Lock();self.last_seen=0;self.callbacks=[]
    async def close(self):
        if self.feed:self.feed.cancel();await asyncio.gather(self.feed,return_exceptions=True);self.feed=None
        if self.player:
            event=getattr(self.player,'_HumanPlayer__thread_quit',None)
            if event:event.set()
            engine.base.clear_queue(self.player.audio._queue);engine.base.clear_queue(self.player.video._queue)
            thread=getattr(self.player,'_HumanPlayer__thread',None)
            if thread:await asyncio.to_thread(thread.join,8)
        if self.pc:await self.pc.close()
        self.pc=None;self.player=None;self.p=None;self.token=None
    def authorize(self,request):
        if not self.token or request.headers.get('X-Trial-Session')!=self.token:raise web.HTTPForbidden()
        self.last_seen=time.monotonic()
    async def offer(self,request):
        async with self.lock:
            if self.pc:raise web.HTTPConflict(text='实验页已有连接，请先断开另一页或等待释放')
            self.p=engine.Presenter(engine.options('isolated-50fps'),self.assets,lambda event:self.callbacks.append(dict(time=time.time(),**event)))
            self.player=HumanPlayer(self.p);self.pc=rtc_manager.RTCPeerConnection();self.token=uuid.uuid4().hex;self.last_seen=time.monotonic()
            try:
                data,_=prepare_local_offer(await request.json())
                await self.pc.setRemoteDescription(RTCSessionDescription(type='offer',sdp=data['sdp']))
                self.pc.addTrack(self.player.audio);self.pc.addTrack(self.player.video)
                self.pc.getTransceivers()[1].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('video').codecs if c.name in ('H264','rtx')])
                await self.pc.setLocalDescription(await self.pc.createAnswer())
                return web.json_response(dict(type='answer',sdp=self.pc.localDescription.sdp,token=self.token))
            except Exception:
                await self.close();raise
    async def command(self,request):
        self.authorize(request);data=await request.json();kind=data.get('kind')
        if kind=='disconnect':
            async with self.lock:await self.close()
        elif kind=='interrupt':
            if self.feed:self.feed.cancel();await asyncio.gather(self.feed,return_exceptions=True);self.feed=None
            self.p.flush_talk()
        elif kind=='speech':
            if self.feed:self.feed.cancel();await asyncio.gather(self.feed,return_exceptions=True)
            self.p.flush_talk();generation=self.p.generation
            async def feed():
                wave,rate=sf.read(ROOT/'assets/calibration-speech-16k-v1.wav',dtype='float32');assert rate==16000
                started=time.monotonic()
                for i in range(60):
                    chunk=wave[(np.arange(2560)+i*2560)%len(wave)]
                    self.p.enqueue_stream(chunk,{'id':'preview-'+str(generation)},start=i==0,end=i==59,generation=generation)
                    await asyncio.sleep(max(0,started+(i+1)*.16-time.monotonic()))
            self.feed=asyncio.create_task(feed())
        elif kind in self.assets.clips and kind!='idle':self.p.request_motion(kind)
        else:raise web.HTTPBadRequest()
        return web.json_response(dict(ok=True))
    async def status(self,request):
        self.authorize(request)
        return web.json_response(dict(stats=self.p.stats,pose=self.p.pose,queue_seconds=self.p.asr.queue.qsize()*.02,
                                      segment_history=self.p.idle_scheduler.history[-20:],callbacks=self.callbacks[-3:]))
    async def monitor(self):
        while True:
            await asyncio.sleep(3)
            if self.pc and (self.pc.connectionState in ('failed','closed') or time.monotonic()-self.last_seen>30):
                async with self.lock:await self.close()

trial=Trial()
async def index(request):return web.FileResponse(HERE/'review.html')
async def live(request):return web.FileResponse(HERE/'live.html')
async def rtc(request):return web.json_response(dict(iceServers=cloud_runtime.ice_servers()))
async def start(app):
    def warm():
        assets=engine.Assets()
        # Touch each mapped page before first viewer, rather than faulting during gestures.
        for frames in assets.full_frames.values():
            int(frames.reshape(-1)[::4096].sum(dtype=np.uint64))
        probe=engine.Presenter(engine.options('startup-warmup'),assets,lambda e:None)
        probe.asr.run_step();features=probe.asr.feat_queue.get(timeout=2)
        for name in assets.clips:
            tokens=[(name,i) for i in range(4)];pred=probe._infer(tokens,features)
            for token,face in zip(tokens,pred):probe._compose(token,face)
        return assets
    trial.assets=await asyncio.to_thread(warm);app['monitor']=asyncio.create_task(trial.monitor())
async def stop(app):
    app['monitor'].cancel();await asyncio.gather(app['monitor'],return_exceptions=True);await trial.close()
app=web.Application(middlewares=[gate]);app.router.add_get('/',index);app.router.add_get('/live',live)
app.router.add_get('/rtc-config',rtc);app.router.add_post('/offer',trial.offer);app.router.add_post('/command',trial.command);app.router.add_get('/status',trial.status)
app.router.add_static('/media/',ROOT/'outputs/presenter-50fps/review',show_index=False)
app.on_startup.append(start);app.on_shutdown.append(stop)
web.run_app(app,host='127.0.0.1',port=8788,access_log=None)
