"""PCM utterance segmentation and explicit wake-prefix matching; no model/tool side effects."""
from collections import deque
import array
import io
import math
import re
import sys
import wave

WAKE_WORD='小霖小霖'
WELCOME='我在，请问有什么可以帮您？'
TIMEOUT_SECONDS=60

def wake_question(text):
    # Accept common ASR homophones only at the beginning of an utterance.
    match=re.match(r'^\s*(?:(?:你好|喂|嘿)[\s，,！!。]*)?小[霖林琳麟][\s，,。！!、]*小[霖林琳麟](?=$|[\s，,。！!？?、]|[\u4e00-\u9fffA-Za-z0-9])',text)
    if not match:return None
    return text[match.end():].lstrip(' ，,。！!？?、：:').strip()

def wav_bytes(pcm):
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(pcm)
    return output.getvalue()

class WakeBuffer:
    def __init__(self):self.reset()
    def reset(self):
        self.preroll=deque(maxlen=3);self.parts=[];self.seconds=0.;self.silence=0.;self.speech=0.
    def feed(self,pcm):
        samples=array.array('h');samples.frombytes(pcm)
        if sys.byteorder!='little':samples.byteswap()
        duration=len(samples)/16000
        rms=math.sqrt(sum(float(x)*x for x in samples)/max(1,len(samples)))/32768
        speaking=rms>=.008
        if not self.parts:
            if not speaking:self.preroll.append(pcm);return None
            self.parts=list(self.preroll);self.preroll.clear();self.parts.append(pcm)
            self.seconds=sum(len(part) for part in self.parts)/32000;self.speech=duration;return None
        self.parts.append(pcm);self.seconds+=duration
        if speaking:self.silence=0.;self.speech+=duration
        else:self.silence+=duration
        if self.seconds>=12 or self.silence>=.6:
            result=b''.join(self.parts) if self.speech>=.2 else None
            self.reset();return result
        return None
