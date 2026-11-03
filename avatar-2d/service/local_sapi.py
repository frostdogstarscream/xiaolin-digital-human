"""Offline Chinese Windows speech provider implementing Fay's Speech interface."""
import json
import subprocess
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'


class Speech:
    def connect(self):
        return None

    def close(self):
        return None

    def to_sample(self,text,style=None):
        key=uuid.uuid4().hex
        jobs=ROOT/'runtime/tts-jobs'
        jobs.mkdir(parents=True,exist_ok=True)
        target=FAY/'samples'/('sapi-'+key+'.wav')
        job=jobs/(key+'.json')
        job.write_text(json.dumps({'text':str(text),'output':str(target)},ensure_ascii=False),encoding='utf-8')
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',
                        str(ROOT/'service/speak_sapi.ps1'),'-JobFile',str(job)],
                       check=True,capture_output=True,timeout=90)
        if not target.is_file() or target.stat().st_size<100:
            raise RuntimeError('Offline TTS did not produce audio')
        return str(target)
