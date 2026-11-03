"""Fay console with the pinned native LiveTalking MelASR / HumanPlayer / RTCManager."""
import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import app as legacy
from aiohttp import web
from realtime_ingress import RealtimeIngress

ROOT = legacy.ROOT
legacy.PORT = int(os.environ.get('AVATAR_PORT', '8766'))


class LiveBridge(RealtimeIngress,legacy.Bridge):
    def __init__(self):
        super().__init__()
        self.assets = None
        self.rtc = None
        self.presenter = None
        self.offer_lock = asyncio.Lock()
        self.sessionid = None
        self.selected_action = 'auto'
        self.user_to_viewer = None
        self.asr_requests = 0
        self.rtc_debug = {}
        from wake_word import WakeGate
        self.wake_gate=WakeGate()
        self.voice_task=None
        self.voice_turn=None
        self.voice_stage='idle'
        self.setup_realtime(ROOT,legacy.PORT)

    async def emit(self,event,**data):
        if event=='answer_complete' and self.voice_turn and self.voice_turn['epoch']==self.epoch:
            from wake_word import canonical
            self.voice_turn['expected']=canonical(data.get('text',''))
            self.check_voice_complete()
        if event=='error' and self.voice_turn and not self.voice_turn['future'].done():
            self.voice_turn['future'].set_result(False)
        await super().emit(event,**data)

    def check_voice_complete(self):
        turn=self.voice_turn
        if turn and turn['expected'] and turn['expected'] in turn['played'] and not turn['future'].done():
            turn['future'].set_result(True)

    async def work(self):
        try:
            from live_engine import Assets, RTCManager, options, session_manager
            import logging
            logging.getLogger('aioice.ice').setLevel(logging.INFO)
            self.assets = await asyncio.get_running_loop().run_in_executor(self.executor, Assets)
            self.rtc = RTCManager(options())
            self.manager = session_manager
            self.manager.set_max_session(1)
            self.manager.init_builder(self.build_presenter)
            self.model_state = 'ready'
            await self.emit('model_ready')
        except Exception as exc:
            print('LiveTalking initialization failed:', type(exc).__name__, str(exc), flush=True)
            self.model_state = 'error'
            await self.emit('error', message='LiveTalking 模型初始化失败，请检查本机日志。')

    def build_presenter(self, sessionid, params):
        from live_engine import Presenter, options
        def callback(info):
            asyncio.run_coroutine_threadsafe(self.packet_event(info), self.loop)
        self.presenter = Presenter(options(sessionid), self.assets, callback)
        return self.presenter

    async def startup(self, application):
        self.loop = asyncio.get_running_loop()
        await super().startup(application)

    async def shutdown(self, application):
        if self.voice_task and not self.voice_task.done():
            self.voice_task.cancel()
            await asyncio.gather(self.voice_task,return_exceptions=True)
        if self.rtc:
            await self.rtc.shutdown()
        await super().shutdown(application)

    async def close_rtc(self):
        self.wake_gate.reset()
        if self.presenter:
            self.presenter.flush_talk()
        if self.rtc:
            await self.rtc.shutdown()
        if self.sessionid:
            self.manager.remove_session(self.sessionid)
        self.presenter = None
        self.sessionid = None

    async def offer(self, request):
        viewer = request.headers.get('X-Avatar-Viewer')
        if not viewer or viewer not in self.viewer_ids.values():
            raise web.HTTPForbidden(text='请先连接控制台')
        if self.model_state != 'ready':
            raise web.HTTPServiceUnavailable(text='LiveTalking 还在准备')
        params=await request.json()
        from rtc_compat import prepare_local_offer,OfferPayload
        prepared,mdns_fallback=prepare_local_offer(params)
        candidates=[line for line in str(params.get('sdp','')).splitlines() if line.startswith('a=candidate:')]
        agent=request.headers.get('User-Agent','')
        self.rtc_debug=dict(browser='Firefox' if 'Firefox/' in agent else 'Chromium' if 'Chrome/' in agent else 'other',
                            offer_candidates=len(candidates),mdns_candidates=sum('.local ' in line for line in candidates),
                            mdns_half_trickle=mdns_fallback,phase='server_offer',time=time.time())
        async with self.offer_lock:
            await self.interrupt('viewer_connect')
            await self.close_rtc()
            await self.claim_viewer(request)
            try:
                response = await self.rtc.handle_offer(OfferPayload(prepared))
                self.sessionid = json.loads(response.text).get('sessionid')
                if not self.sessionid:
                    raise ValueError('No RTC session')
                answer_lines=json.loads(response.text).get('sdp','').splitlines()
                self.rtc_debug.update(phase='server_answer',answer_candidates=sum(line.startswith('a=candidate:') for line in answer_lines),
                    media=[line for line in answer_lines if line.startswith('m=')])
                if not self.rtc_debug['answer_candidates']:
                    from aiortc import RTCPeerConnection,RTCConfiguration
                    probe=RTCPeerConnection(RTCConfiguration(iceServers=[]))
                    try:
                        probe.addTransceiver('audio',direction='recvonly')
                        await probe.setLocalDescription(await probe.createOffer())
                        self.rtc_debug['same_process_candidate_probe']=sum(line.startswith('a=candidate:') for line in probe.localDescription.sdp.splitlines())
                    finally:await probe.close()
                return response
            except Exception as exc:
                self.rtc_debug.update(phase='server_error',error=type(exc).__name__)
                await self.close_rtc()
                raise web.HTTPBadGateway(text='实时展示连接失败，请重试')

    async def rtc_status(self,request):
        if request.headers.get('X-Avatar-Viewer') not in self.viewer_ids.values():
            raise web.HTTPForbidden()
        data=await request.json()
        phase=str(data.get('phase',''))
        if phase not in ('local_offer','gathering','server_offer','remote_answer','connecting','connected'):
            raise web.HTTPBadRequest()
        self.rtc_debug['client_phase']=phase
        self.rtc_debug['client_error']=str(data.get('error',''))[:250]
        return web.json_response({'ok':True})

    async def claim_viewer(self, request):
        viewer = request.headers.get('X-Avatar-Viewer')
        if viewer and viewer in self.viewer_ids.values() and viewer != self.playback_owner:
            # Commands from a new window must establish its own RTC session first.
            if request.path != '/api/offer':
                raise web.HTTPConflict(text='数字人正在切换到当前窗口，请稍后重试')
        await super().claim_viewer(request)

    def check_rtc(self):
        if not self.presenter or not self.rtc or not any(pc.connectionState == 'connected' for pc in self.rtc.pcs):
            raise web.HTTPConflict(text='数字人音视频正在连接，请稍候')

    async def say(self, request):
        self.check_rtc()
        return await super().say(request)

    async def chat(self, request):
        self.check_rtc()
        return await super().chat(request)

    async def interrupt(self, reason='user'):
        if self.voice_task and not self.voice_task.done() and self.voice_task is not asyncio.current_task():
            self.voice_task.cancel()
            await asyncio.gather(self.voice_task,return_exceptions=True)
        if reason=='viewer_connect':self.wake_gate.reset()
        if self.presenter:
            self.presenter.flush_talk()
        for job in self.jobs.values():
            if job['status'] in ('streaming', 'preparing'):
                job['status'] = 'cancelled'
        await super().interrupt(reason)

    async def voice_state(self,request):
        from wake_word import settings
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict(text='展示已切换到其他窗口')
        config=settings()
        return web.json_response({**self.wake_gate.state(config),'stage':self.voice_stage,
            'busy':bool((self.voice_task and not self.voice_task.done()) or (self.active_http and not self.active_http.done())
                        or any(j['epoch']==self.epoch and j['status'] in ('preparing','streaming') for j in self.jobs.values()))})

    async def voice_input(self,request):
        await self.claim_viewer(request);self.check_rtc()
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict(text='请在当前展示窗口开启语音唤醒')
        data=await request.json();text=str(data.get('text','')).strip()
        if not 1<=len(text)<=300:raise web.HTTPBadRequest(text='请说一句 300 字以内的问题')
        decision=self.wake_gate.accept(text)
        if decision['status']=='waiting':return web.json_response(decision)
        await self.interrupt('voice_input')
        self.voice_task=asyncio.create_task(self.run_voice(request,decision))
        return web.json_response(decision)

    async def run_voice(self,request,decision):
        from wake_word import canonical,VoiceRequest,settings
        try:
            for stage,text in [('welcome',decision.get('welcome','')),('question',decision.get('question',''))]:
                if not text:continue
                self.voice_stage=stage
                self.voice_turn={'epoch':self.epoch+1,'expected':canonical(text) if stage=='welcome' else '',
                                 'played':'','future':self.loop.create_future()}
                method=legacy.Bridge.say if stage=='welcome' else legacy.Bridge.chat
                await method(self,VoiceRequest(request,text))
                if not await asyncio.wait_for(self.voice_turn['future'],timeout=100):
                    raise RuntimeError('Voice turn failed')
                self.voice_turn=None
            self.wake_gate.until=time.monotonic()+settings()['timeout']
        except asyncio.CancelledError:raise
        except Exception:
            await self.emit('error',message='本次语音回复未完成，请重试或使用文字输入。')
        finally:self.voice_turn=None;self.voice_stage='idle'

    async def sleep_voice(self,request):
        await self.claim_viewer(request)
        if request.headers.get('X-Avatar-Viewer')!=self.playback_owner:raise web.HTTPConflict(text='展示已切换到其他窗口')
        self.wake_gate.reset()
        await self.interrupt('voice_sleep')
        return web.json_response({'ok':True})

    async def action(self, request):
        await self.claim_viewer(request)
        data = await request.json()
        action = data.get('action', 'auto')
        if action not in ('auto', 'idle') and action not in (self.assets.clips if self.assets else {}):
            raise web.HTTPBadRequest(text='未知动作')
        self.selected_action = action
        if data.get('play'):
            self.check_rtc()
            if action in self.assets.clips:
                self.presenter.request_motion(action)
        return web.json_response({'ok': True, 'action': action})

    async def asr(self, request):
        viewer=request.headers.get('X-Avatar-Viewer')
        if not viewer or viewer!=self.playback_owner:
            raise web.HTTPConflict(text='数字人正在切换到当前窗口，请稍后重试')
        epoch=self.epoch
        data=await request.read()
        if not 64<=len(data)<=4*1024*1024:
            raise web.HTTPBadRequest(text='录音大小无效，请重新录制')
        try:
            async with self.http.post('http://127.0.0.1:8780/transcribe',data=data,
                    headers={'X-Avatar-ASR':'1'},timeout=legacy.ClientTimeout(total=65)) as response:
                if response.status!=200:
                    if response.status in (400,429,503):
                        raise web.HTTPBadRequest(text=await response.text())
                    raise web.HTTPBadGateway(text='本机识别失败，请重新录音')
                result=await response.json()
        except web.HTTPException:raise
        except Exception:raise web.HTTPServiceUnavailable(text='无法连接本机 FunASR，请检查识别服务') from None
        if epoch!=self.epoch or viewer!=self.playback_owner:
            raise web.HTTPConflict(text='本次录音已取消')
        self.asr_requests+=1
        return web.json_response(result)

    async def speech_config(self,request):
        data=await request.json()
        voice=str(data.get('voice','Cherry')).strip()
        if not legacy.re.fullmatch('[A-Za-z0-9_-]{1,80}',voice):
            raise web.HTTPBadRequest(text='音色 ID 格式不正确')
        config=legacy.configparser.ConfigParser(interpolation=None)
        path=legacy.FAY/'system.conf'
        config.read(path,encoding='utf-8-sig')
        config['key']['bailian_tts_voice']=voice
        temp=path.with_suffix('.speech-tmp')
        with temp.open('w',encoding='utf-8') as output:config.write(output)
        os.replace(temp,path)
        return web.json_response({'ok':True,'voice':voice})

    def public(self, job):
        return {key: job.get(key) for key in ('job_id', 'status', 'text', 'action', 'epoch',
                                             'received_at', 'queued_at', 'started_at', 'ended_at', 'voice_seconds',
                                             'first_delta_at','generation_ended_at','delta_count','transport','model')}

    async def receive(self, payload):
        if payload.get('Topic') != 'human' or payload.get('Username') != legacy.USERNAME:
            return
        data = payload.get('Data') or {}
        if data.get('Key') != 'audio' or not data.get('Value'):
            return
        conv = str(data.get('CONV_ID') or '')
        if not self.accepting or conv in self.blocked or not self.presenter:
            return
        source = Path(str(data['Value'])).resolve()
        streamed_key=(str(source),conv)
        if self.streamed_sources[streamed_key]:
            self.streamed_sources[streamed_key]-=1
            if not self.streamed_sources[streamed_key]:del self.streamed_sources[streamed_key]
            return
        if not source.is_relative_to((legacy.FAY / 'samples').resolve()) or not source.is_file() or source.suffix.lower() not in ('.wav', '.mp3'):
            return
        marker = (conv, str(data.get('CONV_MSG_NO')), str(source))
        if marker in self.seen:
            return
        if self.presenter.asr.queue.qsize() > 16000/320*60:
            await self.emit('error', message='待播语音超过一分钟，请先打断。')
            return
        self.seen.add(marker)
        first = conv not in self.conversations
        self.conversations.add(conv)
        action = (legacy.action_for(data) if self.selected_action == 'auto' else self.selected_action) if first else 'idle'
        key = uuid.uuid4().hex
        job = dict(job_id=key, id=key, status='preparing', text=str(data.get('Text') or data.get('text') or ''),
                   action=action, epoch=self.epoch, received_at=time.time(), cancel=__import__('threading').Event())
        self.jobs[key] = job
        epoch = self.epoch
        try:
            wave = await self.loop.run_in_executor(self.executor, self.decode_audio, source)
            if epoch != self.epoch:
                job['status'] = 'cancelled'
                return
            job.update(status='streaming', queued_at=time.time(), voice_seconds=len(wave)/16000)
            self.presenter.enqueue(wave, dict(job_id=key, epoch=epoch, action=action))
            await self.emit('streaming', **self.public(job))
        except Exception:
            job['status'] = 'error'
            await self.emit('error', message='Fay 语音读取失败。')

    @staticmethod
    def decode_audio(source):
        import numpy as np
        ffmpeg = ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
        result = subprocess.run([str(ffmpeg), '-v', 'error', '-nostdin', '-i', str(source), '-t', '60',
                                 '-f', 'f32le', '-ar', '16000', '-ac', '1', 'pipe:1'],
                                check=True, capture_output=True, timeout=15)
        wave = np.frombuffer(result.stdout, dtype='<f4').copy()
        if not len(wave) or not np.isfinite(wave).all():
            raise ValueError('Invalid speech')
        return wave

    async def packet_event(self, info):
        if info.get('error'):
            await self.emit('error', message=info['error'])
            return
        job = self.jobs.get(info.get('job_id'))
        if not job or job['epoch'] != self.epoch or job['status'] == 'cancelled':
            return
        if info.get('status') == 'start':
            job['started_at'] = time.time()
            await self.emit('playback_started', **self.public(job))
        if info.get('end'):
            job.update(status='ready', ended_at=time.time())
            if self.voice_turn and self.voice_turn['epoch']==job['epoch']:
                from wake_word import canonical
                self.voice_turn['played']+=canonical(job.get('text',''))
                self.check_voice_complete()
            if job['epoch'] in self.completed_chats:
                self.dialogue_verified = True
            await self.emit('playback_ended', **self.public(job))

    async def health(self, request):
        response = await super().health(request)
        data = json.loads(response.text)
        data.update(backend='LiveTalking', transport='WebRTC', native_source=str(SOURCE_NAME),
                    sessionid=self.sessionid, selected_action=self.selected_action,
                    rtc_connected=bool(self.rtc and any(pc.connectionState == 'connected' for pc in self.rtc.pcs)),
                    render_stats=self.presenter.stats if self.presenter else {},
                    render_error=self.presenter.error if self.presenter else None,
                    audio_queue=self.presenter.asr.queue.qsize() if self.presenter else 0,
                    device=self.assets.device if self.assets else None,
                    precision=str(self.assets.dtype) if self.assets else None)
        data['rtc_debug']={**self.rtc_debug,'peers':[dict(connection=p.connectionState,ice=p.iceConnectionState,gathering=p.iceGatheringState,
            tracks=[dict(kind=t.kind,direction=t.direction,current=t.currentDirection,local_candidates=len(t.receiver.transport.transport.iceGatherer.getLocalCandidates()),remote_candidates=len(t.receiver.transport.transport.getRemoteCandidates())) for t in p.getTransceivers()]) for p in self.rtc.pcs]} if self.rtc else {}
        try:
            async with self.http.get('http://127.0.0.1:8780/health',timeout=legacy.ClientTimeout(total=1)) as response:
                data['asr']=await response.json()
        except Exception:data['asr']={'backend':'FunASR','state':'offline'}
        from bailian_speech import settings
        try:
            speech=settings()
            data['speech']={'provider':data['provider']['tts'],'model':speech['realtime_model'] if speech['realtime'] else speech['model'],
                'voice':speech['voice'],'streaming':speech['realtime'],'transport':'WebSocket/PCM' if speech['realtime'] else 'HTTP/file'}
        except Exception:data['speech']={'provider':data['provider']['tts']}
        data['wake']=self.wake_gate.state()
        return web.json_response(data)


SOURCE_NAME = 'c7269433a2b6ecebcd9342445d2ecc882c98b0da'


def main():
    bridge = LiveBridge()
    application = web.Application(middlewares=[legacy.local_only], client_max_size=4*1024*1024)
    application.on_startup.append(bridge.startup)
    application.on_cleanup.append(bridge.shutdown)
    async def index(request):
        return web.FileResponse(ROOT/'web/live.html')
    async def rest(request):
        return web.FileResponse(ROOT/'runtime/avatars/presenter_v1__welcome-wave/full_imgs/00000000.png')
    async def script(request):
        return web.FileResponse(ROOT/'web/live.js')
    async def microphone_script(request):
        return web.FileResponse(ROOT/'web/microphone.js')
    async def listening_script(request):
        return web.FileResponse(ROOT/'web/voice-listening.js')
    application.add_routes([web.get('/', index), web.get('/rest.png', rest),
        web.get('/live.js', script),
        web.get('/microphone.js', microphone_script),
        web.get('/voice-listening.js',listening_script),
        web.get('/api/health', bridge.health), web.get('/ws', bridge.socket),
        web.post('/api/offer', bridge.offer), web.post('/api/start', bridge.start_core),
        web.post('/api/rtc-status', bridge.rtc_status),
        web.post('/api/say', bridge.say), web.post('/api/chat', bridge.chat),
        web.post('/api/action', bridge.action), web.post('/api/interrupt', bridge.cancel),
        web.post('/api/asr', bridge.asr), web.post('/api/speech-config', bridge.speech_config),
        web.post('/api/voice-input', bridge.voice_input),web.post('/api/voice-state',bridge.voice_state),
        web.post('/api/voice-sleep',bridge.sleep_voice),
        web.post('/api/tts/begin',bridge.tts_begin),web.post('/api/tts/packet',bridge.tts_packet),web.post('/api/tts/end',bridge.tts_end),
        web.post('/api/provider', bridge.configure)])
    web.run_app(application, host='127.0.0.1', port=legacy.PORT, access_log=None)


if __name__ == '__main__':
    main()
