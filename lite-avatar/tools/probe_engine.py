import json
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
from engine import LiteEngine,WORKSPACE

engine=LiteEngine()
source=WORKSPACE/'fay-ue4/runtime/fay-local/app/samples/bailian-4d5c8233594740b285bb34d25bda1c98.wav'
result=engine.render(source,'idle',ROOT/'outputs/first-speech',threading.Event())
result['loaded_seconds']=engine.loaded_seconds
(ROOT/'outputs/engine-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
