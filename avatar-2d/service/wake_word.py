"""Local transcript wake gate shared by browser voice turns and configuration."""
import json
import re
import time
from pathlib import Path

CONFIG=Path(__file__).resolve().parents[2]/'fay-ue4/runtime/fay-local/app/config.json'
DEFAULT_REPLY='您好，我是小霖，很高兴为您服务，请问有什么可以帮您？'


def canonical(text):
    return ''.join(re.findall(r'[A-Za-z0-9\u3400-\u9fff]+',str(text))).lower()


def settings():
    source=json.loads(CONFIG.read_text(encoding='utf-8-sig')).get('source',{})
    return dict(enabled=bool(source.get('wake_word_enabled',True)),word=source.get('wake_word','小霖小霖'),
                aliases=source.get('wake_word_aliases',[]),reply=source.get('wake_reply',DEFAULT_REPLY),timeout=60)


class WakeGate:
    def __init__(self):self.until=0.
    def reset(self):self.until=0.
    def state(self,config=None):
        config=config or settings()
        return dict(enabled=config['enabled'],word=config['word'],awake=not config['enabled'] or time.monotonic()<self.until,
                    timeout_seconds=config['timeout'])
    def accept(self,text,config=None,now=None):
        config=config or settings();now=time.monotonic() if now is None else now
        words=[x.strip() for x in config['word'].replace('，',',').split(',') if x.strip()]
        words.extend(x for x in config.get('aliases',[]) if isinstance(x,str) and x.strip())
        # Matching removes ASR punctuation but requires the complete repeated name.
        pattern=None
        for word in words:
            candidate=r'[\s，,。.!！?？、]*'.join(map(re.escape,word))
            if re.search(candidate,text):pattern=candidate;break
        if pattern:
            question=re.sub(pattern,'',text,count=1).strip(' \t\r\n，,。.!！?？、：:')
            self.until=now+config['timeout']
            return dict(status='waking',welcome=config['reply'],question=question)
        if not config['enabled'] or now<self.until:
            self.until=now+config['timeout']
            return dict(status='question',question=text)
        return dict(status='waiting',question='',prompt='请先说“'+config['word']+'”唤醒小霖。')


class VoiceRequest:
    def __init__(self,request,text):self.headers=request.headers;self.path=request.path;self.text=text
    async def json(self):return {'text':self.text}
