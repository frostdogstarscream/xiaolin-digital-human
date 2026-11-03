"""Loopback FunASR/SenseVoice service with HTTP audio and Fay URL-WS adapters."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()

import asyncio
import io
import json
import os
import re
import subprocess
import tempfile
import time

from aiohttp import web,WSMsgType
import numpy as np
import soundfile as sf

FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
FFMPEG=FAY/'test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
MODEL=ROOT/'models/SenseVoiceSmall'
PORT=8780
LIMIT=4*1024*1024


def decode_audio(data):
    if not 64<=len(data)<=LIMIT:raise ValueError('录音大小无效')
    with tempfile.TemporaryDirectory(prefix='asr-',dir=ROOT/'runtime') as directory:
        source=Path(directory)/'recording.bin'
        source.write_bytes(data)
        try:
            result=subprocess.run([str(FFMPEG),'-v','error','-nostdin','-i',str(source),'-t','31',
                                   '-f','f32le','-ar','16000','-ac','1','pipe:1'],
                                  capture_output=True,check=True,timeout=15)
        except Exception:raise ValueError('无法读取录音，请重新录制') from None
    wave=np.frombuffer(result.stdout,dtype='<f4').copy()
    if not 3200<=len(wave)<=30*16000 or not np.isfinite(wave).all():
        raise ValueError('请录制 0.2–30 秒的语音')
    return wave


class Service:
    def __init__(self):
        self.model=None
        self.state='loading'
        self.busy=False
        self.requests=0
        self.task=None

    async def load(self):
        try:
            def build():
                os.environ['HF_HUB_OFFLINE']='1'
                os.environ['MODELSCOPE_OFFLINE']='1'
                os.environ['PATH']=str(FFMPEG.parent)+os.pathsep+os.environ.get('PATH','')
                import torch
                torch.set_num_threads(4)
                from funasr import AutoModel
                from funasr.tokenizer.sentencepiece_tokenizer import SentencepiecesTokenizer
                from funasr.register import tables
                import sentencepiece
                class UnicodeTokenizer(SentencepiecesTokenizer):
                    def _build_sentence_piece_processor(self):
                        if self.sp is None:
                            # SentencePiece's narrow Windows filename API cannot
                            # open the Chinese workspace path. Python reads bytes.
                            self.sp=sentencepiece.SentencePieceProcessor(model_proto=Path(self.bpemodel).read_bytes())
                tables.tokenizer_classes['SentencepiecesTokenizer']=UnicodeTokenizer
                model=AutoModel(model=str(MODEL),device='cpu',ncpu=4,disable_update=True,
                                trust_remote_code=False,disable_pbar=True,disable_log=True)
                # Prepare kernels before a user's first recording.
                model.generate(input=np.zeros(16000,dtype=np.float32),fs=16000,cache={},language='auto',use_itn=True)
                return model
            self.model=await asyncio.to_thread(build)
            self.state='ready'
            print('FunASR SenseVoiceSmall ready on CPU',flush=True)
        except Exception as exc:
            self.state='error'
            print('ASR initialization failed:',type(exc).__name__,str(exc),flush=True)

    async def startup(self,app):self.task=asyncio.create_task(self.load())
    async def cleanup(self,app):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)

    async def health(self,request):
        return web.json_response(dict(backend='FunASR',model='SenseVoiceSmall',state=self.state,
                                      device='cpu',busy=self.busy,requests=self.requests,
                                      audio_uploaded_to_cloud=False,max_seconds=30))

    async def transcribe(self,data):
        if self.state!='ready':raise web.HTTPServiceUnavailable(text='本机语音识别模型尚未就绪')
        if self.busy:raise web.HTTPTooManyRequests(text='正在识别上一段语音，请稍候')
        self.busy=True
        started=time.perf_counter()
        try:
            wave=await asyncio.to_thread(decode_audio,data)
            if float(np.sqrt(np.mean(wave**2)))<0.001:
                return dict(text='',seconds=len(wave)/16000,inference_seconds=0.,empty=True)
            def infer():
                result=self.model.generate(input=wave,fs=16000,cache={},language='auto',
                                           use_itn=True,batch_size_s=30,disable_pbar=True)
                raw=''.join(item.get('text','') for item in result)
                return re.sub(r'<\|[^>]*\|>','',raw).strip()
            text=await asyncio.to_thread(infer)
            self.requests+=1
            return dict(text=text,seconds=len(wave)/16000,inference_seconds=time.perf_counter()-started,
                        empty=not bool(text),backend='FunASR',model='SenseVoiceSmall',cloud_calls=0)
        except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
        except web.HTTPException:raise
        except Exception:raise web.HTTPInternalServerError(text='本机语音识别失败，请重新录制') from None
        finally:self.busy=False

    async def http(self,request):
        if request.headers.get('X-Avatar-ASR')!='1':raise web.HTTPForbidden()
        return web.json_response(await self.transcribe(await request.read()))

    async def websocket(self,request):
        # Compatible with Fay's FunASR.send_url() protocol. Never accept arbitrary
        # filesystem paths or URLs from an unauthenticated browser connection.
        origin=request.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8780','http://localhost:8780'):
            raise web.HTTPForbidden()
        ws=web.WebSocketResponse(max_msg_size=16000)
        await ws.prepare(request)
        async for msg in ws:
            if msg.type!=WSMsgType.TEXT:continue
            try:
                data=json.loads(msg.data)
                if 'url' not in data:continue
                source=Path(str(data['url'])).resolve()
                if not any(source.is_relative_to((FAY/name).resolve()) for name in ['cache_data','samples']):
                    raise ValueError('Invalid audio path')
                if not source.is_file() or source.stat().st_size>LIMIT:raise ValueError('Invalid recording')
                result=await self.transcribe(source.read_bytes())
                await ws.send_str(result['text'])
            except Exception:
                await ws.close(code=1008,message=b'Invalid or unavailable local audio')
                break
        return ws


@web.middleware
async def local_only(request,handler):
    if request.remote not in ('127.0.0.1','::1'):raise web.HTTPForbidden()
    return await handler(request)


def main():
    service=Service()
    app=web.Application(middlewares=[local_only],client_max_size=LIMIT)
    app.add_routes([web.get('/health',service.health),web.post('/transcribe',service.http),web.get('/',service.websocket)])
    app.on_startup.append(service.startup)
    app.on_cleanup.append(service.cleanup)
    web.run_app(app,host='127.0.0.1',port=PORT,access_log=None)


if __name__=='__main__':main()
