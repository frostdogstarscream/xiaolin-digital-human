"""Loopback-only evaluation, frozen audio only; never connects to Fay or a cloud API."""
import asyncio
import gc
import json
import logging
import time
import uuid
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from bootstrap import ROOT,AVATAR,read_json
from aiohttp import web
from engine import load_assets,make_presenter,options
from live_engine import RTCManager,session_manager
from rtc_compat import prepare_local_offer,OfferPayload
import numpy as np
import torch

logging.getLogger('utils.logger').setLevel(logging.WARNING)


@web.middleware
async def local_only(request,handler):
    if request.remote not in ('127.0.0.1','::1'):raise web.HTTPForbidden()
    if request.method not in ('GET','HEAD'):
        if request.headers.get('X-Eval-Request')!='1':raise web.HTTPForbidden()
        if request.headers.get('Origin') not in (None,'http://127.0.0.1:8768','http://localhost:8768'):raise web.HTTPForbidden()
    return await handler(request)


class Evaluation:
    def __init__(self):
        self.assets=None;self.presenter=None;self.rtc=None;self.state='loading';self.backend=None
        self.executor=ThreadPoolExecutor(max_workers=1);self.lock=asyncio.Lock();self.jobs={};self.feed_task=None
        self.owner=None;self.frames=deque(maxlen=300);self.model_error=None;self.load_seconds=None
        self.fixtures={x['id']:x for x in read_json(ROOT/'fixtures/manifest.json')['fixtures']}

    async def startup(self,app):
        self.loop=asyncio.get_running_loop();self.loader=asyncio.create_task(self.switch('wav2lip'))

    async def cleanup(self,app):
        await self.interrupt()
        if self.rtc:await self.rtc.shutdown()
        if self.loader and not self.loader.done():await self.loader
        self.executor.shutdown(wait=True,cancel_futures=True)

    async def interrupt(self):
        if self.feed_task and not self.feed_task.done():
            self.feed_task.cancel();await asyncio.gather(self.feed_task,return_exceptions=True)
        if self.presenter:self.presenter.flush_talk()
        for j in self.jobs.values():
            if j['status'] in ('queued','streaming'):j['status']='cancelled'

    async def close(self):
        await self.interrupt()
        if self.rtc:await self.rtc.shutdown()
        for sid in list(session_manager.sessions):session_manager.remove_session(sid)
        self.rtc=None;self.presenter=None;self.frames.clear()

    async def switch(self,backend):
        async with self.lock:
            self.state='loading';self.model_error=None
            await self.close()
            if self.assets:self.assets.frame.cache_clear()
            self.assets=None;gc.collect()
            if torch.cuda.is_available():torch.cuda.empty_cache()
            try:
                started=time.perf_counter()
                self.assets=await self.loop.run_in_executor(self.executor,load_assets,backend)
                self.backend=backend;self.load_seconds=time.perf_counter()-started
                self.rtc=RTCManager(options());session_manager.set_max_session(1)
                session_manager.init_builder(self.build)
                if torch.cuda.is_available():torch.cuda.reset_peak_memory_stats()
                self.state='ready'
            except Exception as error:
                logging.exception('Candidate load failed')
                self.model_error=type(error).__name__;self.state='error'

    def build(self,sessionid,params):
        self.presenter=make_presenter(self.assets,lambda info:self.loop.call_soon_threadsafe(self.event,info),sessionid)
        self.presenter.video_callback=lambda frame,token,speaking:self.frame_event(token,speaking)
        return self.presenter

    def frame_event(self,token,speaking):
        now=time.time();self.frames.append(now)
        if not speaking:return
        for j in reversed(list(self.jobs.values())):
            if j['status']=='streaming' and j['generation']==self.presenter.generation:
                j.setdefault('first_video_at',now)
                if 'first_pose' not in j:j['first_pose']=list(token)
                j['last_pose']=list(token)
                break

    def event(self,info):
        if info.get('error'):self.model_error=info['error'];return
        job=self.jobs.get(info.get('job_id'))
        if not job or job['status']=='cancelled':return
        if info.get('status')=='start':job['first_audio_at']=time.time()
        if info.get('end'):job.update(status='ready',ended_at=time.time())

    async def offer(self,request):
        if self.state!='ready' or self.lock.locked():raise web.HTTPServiceUnavailable(text='模型准备中')
        params=await request.json()
        await self.close()
        self.rtc=RTCManager(options());session_manager.set_max_session(1);session_manager.init_builder(self.build)
        self.owner=request.headers.get('X-Eval-Client','')
        prepared,_=prepare_local_offer(params)
        return await self.rtc.handle_offer(OfferPayload(prepared))

    def require_owner(self,request):
        if not self.owner or request.headers.get('X-Eval-Client')!=self.owner:raise web.HTTPConflict(text='请先连接当前评估窗口')

    async def play(self,request):
        self.require_owner(request)
        if not self.presenter or not any(pc.connectionState=='connected' for pc in self.rtc.pcs):raise web.HTTPConflict(text='请先连接音视频')
        data=await request.json();fixture=data.get('fixture','short');action=data.get('action','idle')
        if fixture not in self.fixtures or action not in ('idle',*self.assets.clips):raise web.HTTPBadRequest()
        await self.interrupt()
        with wave.open(str(ROOT/self.fixtures[fixture]['file'])) as stream:raw=stream.readframes(stream.getnframes())
        wave_data=np.frombuffer(raw,'<i2').astype(np.float32)/32768
        wave_data=np.pad(wave_data,(0,(-len(wave_data))%320))
        key=uuid.uuid4().hex
        job={'id':key,'backend':self.backend,'fixture':fixture,'action':action,'status':'queued','submitted_at':time.time(),
            'generation':self.presenter.generation,'seconds':len(wave_data)/16000}
        self.jobs[key]=job
        if len(self.jobs)>100:self.jobs.pop(next(iter(self.jobs)))
        async def feed():
            # Let the native render worker finish flushing its previous batch.
            # Otherwise its old-generation batch can consume/drop the first new packet.
            while self.presenter.reset_requested.is_set():await asyncio.sleep(.005)
            job['status']='streaming';started=time.perf_counter()
            for i in range(0,len(wave_data),1600):
                if job['generation']!=self.presenter.generation:return
                self.presenter.enqueue_stream(wave_data[i:i+1600],{'job_id':key,'action':action},start=i==0,
                    end=i+1600>=len(wave_data),generation=job['generation'])
                delay=started+(i+1600)/16000-time.perf_counter()
                if delay>0:await asyncio.sleep(delay)
        self.feed_task=asyncio.create_task(feed())
        return web.json_response(job)

    async def action(self,request):
        self.require_owner(request);data=await request.json()
        action=data.get('action')
        if action not in self.assets.clips:raise web.HTTPBadRequest()
        self.presenter.request_motion(action);return web.json_response({'ok':True})

    async def stop(self,request):
        self.require_owner(request);await self.interrupt();return web.json_response({'ok':True})

    async def set_backend(self,request):
        data=await request.json();backend=data.get('backend')
        if backend not in ('wav2lip','musetalk'):raise web.HTTPBadRequest()
        if self.lock.locked():raise web.HTTPConflict(text='后端切换中')
        if backend!=self.backend or self.state!='ready':self.loader=asyncio.create_task(self.switch(backend))
        return web.json_response({'ok':True})

    async def health(self,request):
        times=list(self.frames)
        return web.json_response({'state':self.state,'backend':self.backend,'error':self.model_error,
            'load_seconds':self.load_seconds,'rtc_connected':bool(self.rtc and any(p.connectionState=='connected' for p in self.rtc.pcs)),
            'fps':(len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0,
            'stats':self.presenter.snapshot() if self.presenter else {},'queue':self.presenter.asr.queue.qsize() if self.presenter else 0,
            'gpu_allocated_mb':torch.cuda.memory_allocated()/1024**2 if torch.cuda.is_available() else 0,
            'gpu_peak_mb':torch.cuda.max_memory_allocated()/1024**2 if torch.cuda.is_available() else 0,
            'jobs':list(self.jobs.values())[-40:],'fixtures':list(self.fixtures.values()),
            'actions':list(self.assets.clips) if self.assets else [],'production_mutations':False,'cloud_calls':0})


def main():
    evaluation=Evaluation();app=web.Application(middlewares=[local_only],client_max_size=65536)
    app.on_startup.append(evaluation.startup);app.on_cleanup.append(evaluation.cleanup)
    async def index(request):return web.FileResponse(ROOT/'web/index.html')
    async def client(request):return web.FileResponse(ROOT/'web/client.js')
    async def rest(request):return web.FileResponse(AVATAR/'runtime/avatars/presenter_v1__welcome-wave/full_imgs/00000000.png')
    app.add_routes([web.get('/',index),web.get('/client.js',client),web.get('/rest.png',rest),web.get('/api/health',evaluation.health),
        web.post('/api/offer',evaluation.offer),web.post('/api/backend',evaluation.set_backend),web.post('/api/play',evaluation.play),
        web.post('/api/action',evaluation.action),web.post('/api/interrupt',evaluation.stop),web.static('/outputs/',ROOT/'outputs',show_index=False)])
    web.run_app(app,host='127.0.0.1',port=8768,access_log=None)


if __name__=='__main__':main()
