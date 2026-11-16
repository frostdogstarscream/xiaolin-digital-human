"""Fay Speech adapter for Bailian Qwen TTS; credentials stay in Fay system.conf."""
import configparser
import re
import subprocess
import tempfile
import uuid
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
FAY = ROOT.parent/'fay-ue4/runtime/fay-local/app'
FFMPEG = FAY/'test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'


def settings():
    config = configparser.ConfigParser(interpolation=None)
    config.read(FAY/'system.conf',encoding='utf-8-sig')
    key = config['key']
    base = urlsplit(key.get('bailian_tts_base_url','') or key.get('gpt_base_url',''))
    host = base.hostname or ''
    if base.scheme!='https' or not (host in ('dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com') or host.endswith('.maas.aliyuncs.com')):
        raise RuntimeError('请配置百炼官方 HTTPS 服务地址')
    return dict(api_key=key.get('bailian_tts_api_key',key.get('gpt_api_key','')).strip(),
                endpoint=urlunsplit(('https',base.netloc,'/api/v1/services/aigc/multimodal-generation/generation','','')),
                model=key.get('bailian_tts_model','qwen3-tts-flash'),
                realtime=key.getboolean('bailian_tts_realtime_enabled',fallback=False),
                realtime_model=key.get('bailian_tts_realtime_model','qwen3-tts-flash-realtime'),
                realtime_url='wss://'+('dashscope-intl.aliyuncs.com' if 'intl' in host else 'dashscope.aliyuncs.com')+'/api-ws/v1/realtime',
                voice=key.get('bailian_tts_voice','Cherry'))


class Speech:
    def __init__(self):self.realtime_lock=threading.Lock()
    def connect(self):pass
    def close(self):pass

    def to_sample(self,text,style=None,context=None):
        value=settings()
        if not value['api_key']:
            raise RuntimeError('百炼密钥尚未配置')
        if not 1<=len(str(text))<=600:
            raise RuntimeError('百炼语音单段文字需在 1–600 字内')
        if value['realtime'] and context and context.get('user')=='Avatar2D':
            from realtime_tts import stream_sample,RealtimeUnavailable
            try:
                with self.realtime_lock:return stream_sample(str(text),context,value)
            except RealtimeUnavailable:pass
        # Never log provider response bodies, signed audio URLs or credentials.
        try:
            response=requests.post(value['endpoint'],json={
                'model':value['model'],'input':{'text':str(text),'voice':value['voice'],'language_type':'Chinese'}},
                headers={'Authorization':'Bearer '+value['api_key']},timeout=(10,75))
            if response.status_code!=200:
                code=re.sub('[^A-Za-z0-9_.-]','',str(response.json().get('code','unknown')))[:80]
                raise RuntimeError(f'百炼 TTS 调用失败 HTTP {response.status_code} ({code})')
            audio=response.json().get('output',{}).get('audio',{})
            url=urlsplit(audio.get('url',''))
            if url.scheme not in ('http','https') or not (url.hostname or '').endswith('.aliyuncs.com'):
                raise RuntimeError('百炼 TTS 未返回有效音频')
            # Provider examples include HTTP URLs; fetch the same object with TLS.
            url=urlunsplit(('https',url.netloc,url.path,url.query,''))
            target=FAY/'samples'/('bailian-'+uuid.uuid4().hex+'.wav')
            target.parent.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='bailian-tts-',dir=ROOT/'runtime') as temp:
                source=Path(temp)/'source.wav'
                with requests.get(url,stream=True,timeout=(10,60),allow_redirects=False) as download:
                    if download.status_code!=200:raise RuntimeError('百炼 TTS 音频下载失败')
                    size=0
                    with source.open('wb') as out:
                        for chunk in download.iter_content(65536):
                            size+=len(chunk)
                            if size>20*1024*1024:raise RuntimeError('合成音频超出大小限制')
                            out.write(chunk)
                subprocess.run([str(FFMPEG),'-v','error','-nostdin','-n','-i',str(source),
                                '-ar','16000','-ac','1','-c:a','pcm_s16le',str(target)],
                               capture_output=True,check=True,timeout=25)
            return str(target)
        except RuntimeError:raise
        except Exception:
            raise RuntimeError('百炼语音服务暂不可用，请检查网络、模型权限和额度') from None
