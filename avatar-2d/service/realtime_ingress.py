"""Authenticated, epoch-bound PCM ingress for the local Fay TTS worker."""
import audioop
import hmac
import json
import re
import secrets
import time
import uuid
from collections import Counter
from pathlib import Path

import numpy as np
from aiohttp import web


class RealtimeIngress:
    def setup_realtime(self,root,port):
        self.tts_token=secrets.token_urlsafe(32)
        self.streamed_sources=Counter()
        self.stream_jobs={}
        path=root/'runtime/realtime-ingress.json'
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'port':port,'token':self.tts_token}),encoding='utf-8')
        temporary.replace(path)

    def tts_auth(self,request,job=False):
        if not hmac.compare_digest(request.headers.get('X-Avatar-TTS',''),self.tts_token):raise web.HTTPForbidden()
        if not job:return
        item=self.stream_jobs.get(request.headers.get('X-Avatar-TTS-Job',''))
        if not item or item['epoch']!=self.epoch or item['status'] not in ('preparing','streaming') or not self.presenter:
            raise web.HTTPConflict(text='实时语音已停止')
        return item

    async def tts_begin(self,request):
        self.tts_auth(request);self.check_rtc()
        data=await request.json();conv=str(data.get('conversation_id') or '')
        filename=str(data.get('file',''));text=str(data.get('text',''))
        if data.get('user')!='Avatar2D' or not re.fullmatch(r'bailian-realtime-[a-f0-9]{32}\.wav',filename) or not 1<=len(text)<=600:
            raise web.HTTPBadRequest()
        if not self.accepting or conv in self.blocked:raise web.HTTPConflict()
        first=conv not in self.conversations;self.conversations.add(conv)
        from app import action_for,FAY
        action=(action_for({'Action':data.get('action')}) if self.selected_action=='auto' else self.selected_action) if first else 'idle'
        key=uuid.uuid4().hex
        job=dict(id=key,job_id=key,text=text,epoch=self.epoch,action=action,status='preparing',received_at=time.time(),
                 generation=self.presenter.generation,seq=0,bytes=0,delta_count=0,rate_state=None,pending=b'',frame_started=False,
                 model=str(data.get('model','')),transport='WebSocket/PCM',conversation=conv,stream_done=False)
        self.jobs[key]=job;self.stream_jobs[key]=job
        self.streamed_sources[(str((FAY/'samples'/filename).resolve()),conv)]+=1
        await self.emit('streaming',**self.public(job))
        return web.json_response({'job_id':key,'epoch':self.epoch})

    def enqueue_pcm(self,job,raw,end=False):
        if not raw and not end:return
        wave=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
        self.presenter.enqueue_stream(wave,{'job_id':job['id'],'epoch':job['epoch'],'action':job['action']},
            start=not job['frame_started'],end=end,generation=job['generation'])
        job['frame_started']=True
        if 'queued_at' not in job:job['queued_at']=time.time()

    async def tts_packet(self,request):
        job=self.tts_auth(request,True)
        if request.headers.get('X-Avatar-TTS-Seq')!=str(job['seq']):raise web.HTTPConflict(text='音频序号不匹配')
        raw=await request.read()
        if not raw or len(raw)%2 or len(raw)>512*1024 or job['bytes']+len(raw)>24000*2*60:raise web.HTTPBadRequest()
        if self.presenter.asr.queue.qsize()>3000:raise web.HTTPTooManyRequests(text='语音队列已满')
        converted,job['rate_state']=audioop.ratecv(raw,2,1,24000,16000,job['rate_state'])
        job['pending']+=converted;job['bytes']+=len(raw);job['seq']+=1;job['delta_count']+=1
        job.setdefault('first_delta_at',time.time())
        job['status']='streaming';job['voice_seconds']=job['bytes']/48000
        # Hold the last packet so only one real final packet carries end=True.
        packet_bytes=self.presenter.chunk*2
        count=max(0,(len(job['pending'])-1)//packet_bytes)*packet_bytes
        if count:
            self.enqueue_pcm(job,job['pending'][:count]);job['pending']=job['pending'][count:]
        return web.json_response({'ok':True})

    async def tts_end(self,request):
        job=self.tts_auth(request,True);data=await request.json()
        if not data.get('ok') or not job['bytes']:
            job['status']='error';self.presenter.flush_talk()
            await self.emit('error',message='百炼实时语音未完成，请重新提问。')
        else:
            job['generation_ended_at']=time.time();job['stream_done']=True
            self.enqueue_pcm(job,job['pending'],end=True);job['pending']=b'';job['rate_state']=None
        return web.json_response({'ok':True})
