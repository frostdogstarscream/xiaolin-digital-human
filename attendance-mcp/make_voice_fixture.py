"""One bounded Bailian synthesis to a local test file; never enters the presenter PCM channel."""
import hashlib
import json
import shutil
import sys
import wave
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'avatar-2d/service'))
from bailian_speech import Speech

def main():
    phrase='小霖小霖，我要打卡。'
    output=ROOT/'runtime/voice-input.wav';metadata=ROOT/'runtime/voice-input.json'
    if metadata.is_file() and output.is_file():
        existing=json.loads(metadata.read_text(encoding='utf-8'))
        if existing.get('text')==phrase and existing['sha256']==hashlib.sha256(output.read_bytes()).hexdigest():
            print(json.dumps(existing,ensure_ascii=True));return
    source=Path(Speech().to_sample(phrase,context=None))
    output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
    with wave.open(str(output),'rb') as audio:
        info=dict(text=phrase,path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  sample_rate=audio.getframerate(),channels=audio.getnchannels(),seconds=audio.getnframes()/audio.getframerate(),
                  synthetic_audio=True,physical_microphone=False,cloud_tts_calls=1)
    metadata.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(info,ensure_ascii=True))

if __name__=='__main__':main()
