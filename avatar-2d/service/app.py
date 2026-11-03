"""Loopback Fay audio/action receiver and local 2D presentation console."""
import asyncio
import configparser
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientSession,ClientTimeout,WSMsgType,web

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
USERNAME='Avatar2D'
FAY_URL='http://127.0.0.1:5000'
PORT=8766
MAP={
 'greeting.hello':'welcome-wave','greeting.welcome':'welcome-wave',
 'farewell.goodbye':'goodbye-wave','dialogue.confirm':'acknowledge-nod',
 'dialogue.explain':'explain-open-palms','dialogue.recommend':'explain-open-palms',
 'dialogue.summary':'explain-open-palms','guidance.invite':'welcome-wave',
}
BEHAVIORS={'nod':'acknowledge-nod','explain':'explain-open-palms','invite':'welcome-wave'}


def model_settings():
    c=configparser.ConfigParser(interpolation=None)
    c.read(FAY/'system.conf',encoding='utf-8-sig')
    k=c['key']
    endpoint=k.get('gpt_base_url','')
    host=urlsplit(endpoint).hostname or ''
    return dict(configured=bool(k.get('gpt_api_key','').strip()),model=k.get('gpt_model_engine',''),
                base_url=endpoint if host.endswith('aliyuncs.com') else '',tts=k.get('tts_module',''))


def action_for(data):
    signal=data.get('Action') or {}
    return MAP.get(signal.get('code'),BEHAVIORS.get(signal.get('behavior'),'idle')) if isinstance(signal,dict) else 'idle'


@web.middleware
async def local_only(request,handler):
    if request.remote not in ('127.0.0.1','::1'):
        raise web.HTTPForbidden(text='Local access only')
    if request.method not in ('GET','HEAD'):
        if request.headers.get('X-Avatar-Client')!='1':raise web.HTTPForbidden(text='Missing local client header')
        origin=request.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
            raise web.HTTPForbidden(text='Unexpected origin')
    try:return await handler(request)
    except web.HTTPException:raise
    except Exception:
        # No provider keys, upstream response bodies, or submitted credentials in logs/errors.
        return web.json_response({'error':'操作未完成，请查看本机服务状态。'},status=500)


class Bridge:
    def __init__(self):
        self.clients=set();self.queue=asyncio.Queue(maxsize=8);self.jobs={}
        self.epoch=0;self.accepting=True;self.blocked=set();self.conversations=set();self.seen=set()
        self.connected=False;self.renderer=None;self.model_state='loading';self.current=None
        self.completed_chats=set();self.dialogue_verified=False
        self.viewer_ids={};self.playback_owner=None
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='avatar-render')
        self.tasks=[];self.events=[];self.active_http=None

    async def emit(self,event,**data):
        payload={'event':event,'epoch':self.epoch,'playback_owner':self.playback_owner,**data}
        self.events.append(dict(event=event,epoch=self.epoch,time=time.time(),job_id=data.get('job_id')))
        self.events=self.events[-200:]
        for ws in list(self.clients):
            if ws.closed:self.clients.discard(ws);continue
            if event=='ready' and self.viewer_ids.get(ws)!=self.playback_owner:continue
            try:await ws.send_json(payload)
            except ConnectionError:self.clients.discard(ws)

    async def claim_viewer(self,request):
        viewer=request.headers.get('X-Avatar-Viewer')
        if viewer in self.viewer_ids.values() and viewer!=self.playback_owner:
            self.playback_owner=viewer
            await self.emit('playback_owner_changed')

    async def startup(self,app):
        self.http=ClientSession(timeout=ClientTimeout(total=120),trust_env=False)
        self.tasks=[asyncio.create_task(self.listen()),asyncio.create_task(self.work())]

    async def shutdown(self,app):
        if self.current:self.current['cancel'].set()
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.http.close()
        self.executor.shutdown(wait=False,cancel_futures=True)

    async def work(self):
        loop=asyncio.get_running_loop()
        try:
            def load():
                from renderer import Renderer
                return Renderer()
            self.renderer=await loop.run_in_executor(self.executor,load)
            self.model_state='ready'
            await self.emit('model_ready')
        except Exception:
            self.model_state='error'
            await self.emit('error',message='口型模型加载失败，请检查本机运行日志。')
            return
        while True:
            job=await self.queue.get()
            if job['epoch']!=self.epoch or job['cancel'].is_set():
                job['status']='cancelled';self.queue.task_done();continue
            self.current=job;job['status']='rendering'
            await self.emit('rendering',job_id=job['id'],text=job['text'],action=job['action'])
            try:
                report=await loop.run_in_executor(self.executor,self.renderer.render,
                    job['source'],job['action'],ROOT/'runtime/sessions'/job['id'],job['cancel'])
                if job['epoch']!=self.epoch or job['cancel'].is_set():job['status']='cancelled'
                else:
                    job.update(status='ready',report=report)
                    if job['epoch'] in self.completed_chats:self.dialogue_verified=True
                    await self.emit('ready',**self.public(job))
            except Exception:
                if job['cancel'].is_set() or job['epoch']!=self.epoch:job['status']='cancelled'
                else:
                    job['status']='error'
                    await self.emit('error',job_id=job['id'],message='本段口型生成失败，请重试或缩短文本。')
            finally:self.current=None;self.queue.task_done()

    def public(self,job):
        key=job['id']
        return dict(job_id=key,status=job['status'],text=job['text'],action=job['action'],
                    video=f'/output/{key}/speaking.mp4',rest=f'/output/{key}/rest.png',
                    epoch=job['epoch'],report=job.get('report'))

    async def receive(self,payload):
        if payload.get('Topic')!='human' or payload.get('Username')!=USERNAME:return
        data=payload.get('Data') or {}
        if data.get('Key')!='audio' or not data.get('Value'):return
        conv=str(data.get('CONV_ID') or '')
        if not self.accepting or conv in self.blocked:return
        source=Path(str(data['Value'])).resolve()
        if not source.is_relative_to((FAY/'samples').resolve()) or source.suffix.lower() not in ('.wav','.mp3') or not source.is_file():
            await self.emit('error',message='Fay 音频不是本机 samples 目录中的有效文件。');return
        marker=(conv,str(data.get('CONV_MSG_NO')),str(source))
        if marker in self.seen:return
        if self.queue.full():
            await self.emit('error',message='播报队列已满，请先打断或等待。');return
        first=conv not in self.conversations
        self.conversations.add(conv);self.seen.add(marker)
        job=dict(id=uuid.uuid4().hex,source=source,text=str(data.get('Text') or ''),
                 action=action_for(data) if first else 'idle',epoch=self.epoch,
                 cancel=threading.Event(),status='queued',conversation=conv)
        self.jobs[job['id']]=job
        await self.queue.put(job)
        await self.emit('queued',**self.public(job))

    async def listen(self):
        while True:
            try:
                async with self.http.ws_connect('ws://127.0.0.1:10002',heartbeat=15) as ws:
                    await ws.send_json({'Username':USERNAME,'Output':True})
                    self.connected=True;await self.emit('fay_connected')
                    async for msg in ws:
                        if msg.type==WSMsgType.TEXT:
                            try:await self.receive(json.loads(msg.data))
                            except (ValueError,TypeError):pass
            except (OSError,asyncio.TimeoutError,ConnectionError):pass
            except asyncio.CancelledError:raise
            except Exception:pass
            self.connected=False;await self.emit('fay_disconnected')
            await asyncio.sleep(2)

    async def interrupt(self,reason='user'):
        self.epoch+=1;self.accepting=False
        self.blocked.update(self.conversations)
        for job in self.jobs.values():
            if job['status'] in ('queued','rendering'):job['cancel'].set();job['status']='cancelled'
        if self.active_http and not self.active_http.done():self.active_http.cancel()
        await self.emit('interrupted',reason=reason)
        try:
            async with self.http.post(FAY_URL+'/to-stop-talking',json={'username':USERNAME},timeout=ClientTimeout(total=3)) as r:
                await r.read()
        except Exception:pass

    async def health(self,request):
        core=False
        try:
            async with self.http.post(FAY_URL+'/api/get-run-status',timeout=ClientTimeout(total=2)) as r:
                core=(await r.json(content_type=None)).get('status') is True
        except Exception:pass
        return web.json_response(dict(fay_connected=self.connected,fay_core=core,model_state=self.model_state,
            provider=model_settings(),dialogue_verified=self.dialogue_verified,playback_owner=self.playback_owner,epoch=self.epoch,queue=self.queue.qsize(),
            jobs=[self.public(j) for j in list(self.jobs.values())[-30:]],events=self.events[-25:]))

    async def start_core(self,request):
        async with self.http.post(FAY_URL+'/api/get-run-status') as r:running=(await r.json(content_type=None)).get('status')
        if not running:
            async with self.http.post(FAY_URL+'/api/start-live') as r:
                if r.status!=200:raise web.HTTPBadGateway(text='Fay 核心启动失败')
                await r.read()
        return web.json_response({'ok':True})

    async def say(self,request):
        await self.claim_viewer(request)
        data=await request.json();text=str(data.get('text','')).strip()
        if not 1<=len(text)<=240:raise web.HTTPBadRequest(text='请输入 1–240 字的播报文本')
        if not self.connected:raise web.HTTPServiceUnavailable(text='Fay 尚未连接')
        await self.interrupt(reason='new_turn');self.accepting=True
        async with self.http.post(FAY_URL+'/transparent-pass',json={'user':USERNAME,'text':text}) as r:
            result=await r.json()
            if r.status!=200 or result.get('code')!=200:raise web.HTTPBadGateway(text='Fay 未接受播报，请启动核心')
        return web.json_response({'ok':True,'epoch':self.epoch})

    async def chat(self,request):
        await self.claim_viewer(request)
        data=await request.json();text=str(data.get('text','')).strip()
        if not 1<=len(text)<=300:raise web.HTTPBadRequest(text='请输入 1–300 字的问题')
        if not model_settings()['configured']:raise web.HTTPConflict(text='请先在本机配置百炼 API Key')
        await self.interrupt(reason='new_turn');self.accepting=True
        epoch=self.epoch
        async def fetch():
            chunks=[]
            try:
                async with self.http.post(FAY_URL+'/v1/chat/completions',json={'model':'fay','user':USERNAME,
                        'stream':True,'messages':[{'role':'user','content':text}]}) as response:
                    if response.status!=200:raise ValueError('Fay returned an error')
                    async for line in response.content:
                        if epoch!=self.epoch:return
                        if not line.startswith(b'data:'):continue
                        raw=line[5:].strip()
                        if raw==b'[DONE]':break
                        obj=json.loads(raw)
                        if 'error' in obj:raise ValueError('Fay model error')
                        for choice in obj.get('choices',[]):
                            delta=choice.get('delta',{}).get('content')
                            if delta:
                                chunks.append(delta)
                                await self.emit('answer',text=delta)
                if not ''.join(chunks).strip():raise ValueError('Empty Fay answer')
                self.completed_chats.add(epoch)
                if any(j['epoch']==epoch and j['status']=='ready' for j in self.jobs.values()):self.dialogue_verified=True
                await self.emit('answer_complete',text=''.join(chunks))
            except asyncio.CancelledError:raise
            except Exception:
                if epoch==self.epoch:await self.emit('error',message='Fay 问答失败，请检查百炼密钥、地域和模型权限。')
        self.active_http=asyncio.create_task(fetch())
        return web.json_response({'ok':True,'epoch':epoch})

    async def cancel(self,request):
        await self.claim_viewer(request)
        await self.interrupt();return web.json_response({'ok':True,'epoch':self.epoch})

    async def configure(self,request):
        data=await request.json()
        key=str(data.get('api_key','')).strip()
        model=str(data.get('model','qwen-plus')).strip()
        endpoint=str(data.get('base_url','https://dashscope.aliyuncs.com/compatible-mode/v1')).strip().rstrip('/')
        u=urlsplit(endpoint)
        if u.scheme!='https' or not (u.hostname=='dashscope.aliyuncs.com' or (u.hostname or '').endswith('.maas.aliyuncs.com')) or u.username or u.password or u.query or u.fragment:
            raise web.HTTPBadRequest(text='请使用百炼官方 HTTPS 兼容接口地址')
        if not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}',model):raise web.HTTPBadRequest(text='模型名称格式不正确')
        c=configparser.ConfigParser(interpolation=None);path=FAY/'system.conf'
        c.read(path,encoding='utf-8-sig')
        if key:c['key']['gpt_api_key']=key
        if not c['key'].get('gpt_api_key'):raise web.HTTPBadRequest(text='请输入 API Key')
        c['key']['gpt_base_url']=endpoint;c['key']['gpt_model_engine']=model
        temp=path.with_suffix('.2d-tmp')
        with temp.open('w',encoding='utf-8') as out:c.write(out)
        os.replace(temp,path)
        self.dialogue_verified=False
        return web.json_response({'ok':True,'provider':model_settings(),'tested':False})

    async def socket(self,request):
        origin=request.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
            raise web.HTTPForbidden()
        ws=web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request);self.clients.add(ws)
        viewer=uuid.uuid4().hex;self.viewer_ids[ws]=viewer
        if self.playback_owner is None:self.playback_owner=viewer
        await ws.send_json({'event':'state','epoch':self.epoch,'model_state':self.model_state,
                            'client_id':viewer,'playback_owner':self.playback_owner})
        try:
            async for msg in ws:
                if msg.type==WSMsgType.TEXT:
                    data=json.loads(msg.data)
                    if self.viewer_ids.get(ws)==self.playback_owner and data.get('event') in ('playback_started','playback_ended','playback_error'):
                        job=self.jobs.get(data.get('job_id'))
                        if job and job['epoch']==self.epoch:
                            job['playback']=data['event'];await self.emit(data['event'],job_id=job['id'])
        finally:
            self.clients.discard(ws);self.viewer_ids.pop(ws,None)
            if self.playback_owner==viewer:
                self.playback_owner=next(iter(self.viewer_ids.values()),None)
                await self.emit('playback_owner_changed')
        return ws


async def output_file(request):
    key=request.match_info['job'];name=request.match_info['name']
    if not re.fullmatch('[0-9a-f]{32}',key) or name not in ('speaking.mp4','rest.png'):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT/'runtime/sessions'/key/name)


async def index(request):return web.FileResponse(ROOT/'web/index.html')


def main():
    b=Bridge();app=web.Application(middlewares=[local_only],client_max_size=32000)
    app.on_startup.append(b.startup);app.on_cleanup.append(b.shutdown)
    app.add_routes([web.get('/',index),web.get('/api/health',b.health),web.get('/ws',b.socket),
        web.post('/api/start',b.start_core),web.post('/api/say',b.say),web.post('/api/chat',b.chat),
        web.post('/api/interrupt',b.cancel),web.post('/api/provider',b.configure),
        web.get('/output/{job}/{name}',output_file)])
    library=json.loads((ROOT/'assets/presenter-v1/motions-v1/action-library.json').read_text(encoding='utf-8'))
    allowed={a['id']:ROOT/a['video'] for a in library['actions'] if a.get('speech_candidate')}
    async def motion(request):
        path=allowed.get(request.match_info['name'])
        if path is None:raise web.HTTPNotFound()
        return web.FileResponse(path)
    async def rest(request):
        return web.FileResponse(ROOT/'runtime/avatars/presenter_v1__welcome-wave/full_imgs/00000000.png')
    async def motion_rest(request):
        key=request.match_info['name']
        if key not in allowed:raise web.HTTPNotFound()
        item=next(a for a in library['actions'] if a['id']==key)
        return web.FileResponse(ROOT/'runtime/avatars'/('presenter_v1__'+key)/'full_imgs'/f"{item['frames']-1:08d}.png")
    app.add_routes([web.get('/motion/{name}',motion),web.get('/motion-rest/{name}',motion_rest),web.get('/rest.png',rest)])
    web.run_app(app,host='127.0.0.1',port=PORT,print=lambda s:print(s,flush=True),access_log=None)


if __name__=='__main__':main()
