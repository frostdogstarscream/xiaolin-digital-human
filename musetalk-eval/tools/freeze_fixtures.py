"""Freeze existing local speech only; never contacts LLM/TTS services."""
import hashlib
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1];WORKSPACE=ROOT.parent
FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    output=ROOT/'fixtures/manifest.json'
    if output.exists():
        existing=json.loads(output.read_text(encoding='utf-8'))
        for item in existing['fixtures']:assert sha(ROOT/item['file'])==item['sha256']
        print('FROZEN_FIXTURES_VERIFIED');return
    samples=WORKSPACE/'fay-ue4/runtime/fay-local/app/samples'
    short=samples/'bailian-4d5c8233594740b285bb34d25bda1c98.wav'
    candidates=[]
    for path in samples.glob('bailian*.wav'):
        if path.stem.endswith('_44k'):continue
        try:
            with wave.open(str(path)) as stream:duration=stream.getnframes()/stream.getframerate()
            if 2<=duration<=25:candidates.append((duration,path.name,path))
        except (wave.Error,EOFError):pass
    if not candidates:raise RuntimeError('No existing speech fixture found')
    unique={}
    for _,_,path in sorted(candidates,reverse=True):unique.setdefault(sha(path),path)
    long=list(unique.values())[:3];items=[]
    for name,sources in [('short',[short]),('long',long)]:
        parts=[subprocess.run([str(FFMPEG),'-v','error','-nostdin','-i',str(source),'-f','s16le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True).stdout for source in sources]
        pcm=(b'\0'*16000).join(parts)
        destination=ROOT/'fixtures'/(name+'.wav')
        with wave.open(str(destination),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(pcm)
        items.append({'id':name,'file':f'fixtures/{name}.wav','sha256':sha(destination),'sources':[{'path':str(p),'sha256':sha(p)} for p in sources],
            'sample_rate':16000,'channels':1,'seconds':len(pcm)/32000,
            'inserted_silence_seconds':.5*(len(parts)-1),'rms':float(np.sqrt(np.mean((np.frombuffer(pcm,'<i2')/32768)**2)))})
    output.write_text(json.dumps({'fixtures':items,'cloud_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(items,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
