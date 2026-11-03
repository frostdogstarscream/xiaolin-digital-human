"""Independent Fay + official LiteAvatar experiment. No LiveTalking imports."""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
sys.path.insert(0,str(WORKSPACE/'avatar-2d/service'))
import app as fay
from aiohttp import web
from wake_word import WakeGate,VoiceRequest,canonical,settings as wake_settings

fay.PORT=8767
fay.USERNAME='LiteAvatarExperiment'
fay.ROOT=ROOT


class LiteBridge(fay.Bridge):
    def __init__(self):
        super().__init__();self.wake_gate=WakeGate();self.voice_task=None;self.voice_turn=None

    async def claim_viewer(self,request):
        if request.headers.get('X-Avatar-Viewer') not in self.viewer_ids.values():raise web.HTTPForbidden(text='请先连接实验版页面')
        await super().claim_viewer(request)

    async def work(self):
        try:
            from engine import LiteEngine
            self.renderer=await asyncio.get_running_loop().run_in_executor(self.executor,LiteEngine)
            import cv2
            cv2.imencode('.png',self.renderer.rest)[1].tofile(ROOT/'runtime/rest.png')
            self.model_state='ready';await self.emit('model_ready')
        except Exception as exc:
            print('LiteAvatar load failed:',type(exc).__name__,str(exc),flush=True)
            self.model_state='error';await self.emit('error',message='LiteAvatar 加载失败，请查看实验版日志。');return
        while True:
            job=await self.queue.get();self.current=job
            try:
                if job['epoch']!=self.epoch:continue
                job['status']='rendering';await self.emit('rendering',**self.public(job))
                report=await self.loop.run_in_executor(self.executor,self.renderer.render,job['source'],'idle',ROOT/'runtime/sessions'/job['id'],job['cancel'])
                if job['epoch']==self.epoch and not job['cancel'].is_set():
                    job.update(status='ready',report=report)
                    if job['epoch'] in self.completed_chats:self.dialogue_verified=True
                    await self.emit('ready',**self.public(job))
            except Exception as exc:
                job['status']='cancelled' if job['cancel'].is_set() else 'error'
                if not job['cancel'].is_set():
                    print('LiteAvatar render failed:',type(exc).__name__,str(exc),flush=True)
                    await self.emit('error',message='本段 LiteAvatar 口型生成失败，请重试。')
            finally:self.current=None;self.queue.task_done()

    async def startup(self,application):
        self.loop=asyncio.get_running_loop();await super().startup(application)

    async def shutdown(self,application):
        if self.voice_task:
            self.voice_task.cancel();await asyncio.gather(self.voice_task,return_exceptions=True)
        await super().shutdown(application)

    async def emit(self,event,**data):
        if event=='playback_owner_changed':
            self.wake_gate.reset()
            await self.interrupt('viewer_changed')
        turn=self.voice_turn
        if turn and turn['epoch']==self.epoch:
            if event=='answer_complete':turn['expected']=canonical(data.get('text',''))
            if event=='playback_ended':turn['played']+=canonical(self.jobs.get(data.get('job_id'),{}).get('text',''))
            if event=='error' and not turn['future'].done():turn['future'].set_result(False)
            if turn['expected'] and turn['expected'] in turn['played'] and not turn['future'].done():turn['future'].set_result(True)
        await super().emit(event,**data)

    async def interrupt(self,reason='user'):
        if self.voice_task and not self.voice_task.done() and self.voice_task is not asyncio.current_task():
            self.voice_task.cancel();await asyncio.gather(self.voice_task,return_exceptions=True)
        await super().interrupt(reason)

    async def asr(self,request):
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict(text='请在当前窗口开启麦克风')
        epoch=self.epoch;data=await request.read()
        if not 64<=len(data)<=4*1024*1024:raise web.HTTPBadRequest(text='录音大小无效')
        async with self.http.post('http://127.0.0.1:8780/transcribe',data=data,headers={'X-Avatar-ASR':'1'},timeout=fay.ClientTimeout(total=65)) as response:
            if response.status!=200:raise web.HTTPBadRequest(text='本机 ASR 未能识别这段录音')
            result=await response.json()
        if epoch!=self.epoch:raise web.HTTPConflict(text='录音已取消')
        return web.json_response(result)

    async def voice_state(self,request):
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict()
        busy=bool(self.voice_task and not self.voice_task.done()) or bool(self.active_http and not self.active_http.done()) or any(
            j['epoch']==self.epoch and (j['status'] in ('queued','rendering') or j['status']=='ready' and j.get('playback')!='playback_ended') for j in self.jobs.values())
        return web.json_response({**self.wake_gate.state(),'busy':busy})

    async def voice_input(self,request):
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict()
        data=await request.json();text=str(data.get('text','')).strip()
        if not 1<=len(text)<=300:raise web.HTTPBadRequest(text='语音文字需为 1–300 字')
        decision=self.wake_gate.accept(text)
        if decision['status']!='waiting':
            await self.interrupt('voice_input');self.voice_task=asyncio.create_task(self.run_voice(request,decision))
        return web.json_response(decision)

    async def run_voice(self,request,decision):
        try:
            for stage,text in [('welcome',decision.get('welcome','')),('question',decision.get('question',''))]:
                if not text:continue
                self.voice_turn={'epoch':self.epoch+1,'expected':canonical(text) if stage=='welcome' else '',
                    'played':'','future':self.loop.create_future()}
                await (self.say if stage=='welcome' else self.chat)(VoiceRequest(request,text))
                if not await asyncio.wait_for(self.voice_turn['future'],120):raise RuntimeError('Playback failed')
                self.voice_turn=None
            self.wake_gate.until=time.monotonic()+wake_settings()['timeout']
        except asyncio.CancelledError:raise
        except Exception:await self.emit('error',message='语音回复未完成，请重试。')
        finally:self.voice_turn=None

    async def voice_sleep(self,request):
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict()
        self.wake_gate.reset();await self.interrupt('voice_sleep');return web.json_response({'ok':True})

    async def health(self,request):
        response=await super().health(request);data=json.loads(response.text)
        from engine import AVATAR_ID
        data.update(backend='LiteAvatar',avatar_id=AVATAR_ID,transport='generated MP4 segments',wake=self.wake_gate.state(),
            render_stats=self.renderer.stats if self.renderer else {},device=self.renderer.device if self.renderer else None)
        try:
            async with self.http.get('http://127.0.0.1:8780/health',timeout=fay.ClientTimeout(total=1)) as r:data['asr']=await r.json()
        except Exception:data['asr']={'state':'offline'}
        data['speech']={'provider':'bailian','streaming':False}
        return web.json_response(data)


def main():
    (ROOT/'runtime').mkdir(exist_ok=True)
    (ROOT/'runtime/sessions').mkdir(exist_ok=True)
    bridge=LiteBridge();application=web.Application(middlewares=[fay.local_only],client_max_size=4*1024*1024)
    application.on_startup.append(bridge.startup);application.on_cleanup.append(bridge.shutdown)
    async def index(request):return web.FileResponse(ROOT/'web/index.html')
    async def rest(request):return web.FileResponse(ROOT/'runtime/rest.png' if (ROOT/'runtime/rest.png').exists() else ROOT/'research/selected-avatar.png')
    async def script(request):return web.FileResponse(ROOT/'web'/request.match_info['name'])
    async def claim(request):
        viewer=request.headers.get('X-Avatar-Viewer')
        if viewer not in bridge.viewer_ids.values():raise web.HTTPForbidden()
        await bridge.claim_viewer(request);return web.json_response({'ok':True})
    application.add_routes([web.get('/',index),web.get('/rest.png',rest),web.get('/ws',bridge.socket),web.get('/api/health',bridge.health),
        web.post('/api/start',bridge.start_core),web.post('/api/claim',claim),web.post('/api/say',bridge.say),web.post('/api/chat',bridge.chat),web.post('/api/interrupt',bridge.cancel),
        web.post('/api/asr',bridge.asr),web.post('/api/voice-input',bridge.voice_input),web.post('/api/voice-state',bridge.voice_state),web.post('/api/voice-sleep',bridge.voice_sleep),
        web.get(r'/{name:[a-z-]+\.js}',script),web.static('/output/',ROOT/'runtime/sessions',show_index=False)])
    web.run_app(application,host='127.0.0.1',port=fay.PORT,access_log=None)


if __name__=='__main__':main()
