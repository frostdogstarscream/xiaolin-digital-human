"""Only process-local paths/runtime. No Fay app import or production writes."""
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
AVATAR=WORKSPACE/'avatar-2d'
SOURCE=Path(json.loads((AVATAR/'source-manifest.json').read_text(encoding='utf-8'))['source_directory'])
FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
sys.path.insert(0,str(AVATAR/'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()
sys.path.insert(0,str(AVATAR/'service'))
sys.path.insert(0,str(SOURCE))
os.chdir(ROOT)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
