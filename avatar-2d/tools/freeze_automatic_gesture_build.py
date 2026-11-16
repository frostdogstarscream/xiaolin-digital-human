"""Freeze changed source and code-only rollback hashes; exclude configs and data."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=ROOT/'avatar-2d/runtime/automatic-gestures'
FILES=['avatar-2d/service/app.py','avatar-2d/service/live_app.py','avatar-2d/service/live_engine.py',
       'avatar-2d/service/realtime_ingress.py','avatar-2d/web/live.html','avatar-2d/web/live.js',
       'fay-ue4/runtime/fay-local/app/core/fay_core.py','fay-ue4/runtime/fay-local/app/gui/flask_server.py',
       'fay-ue4/runtime/fay-local/app/llm/nlp_cognitive_stream.py']

def main():
    entries=[]
    for relative in FILES:
        path=ROOT/relative;old=DIRECTORY/'before'/relative
        if not old.is_file():raise RuntimeError('Missing source rollback: '+relative)
        destination=DIRECTORY/'release'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(path.read_bytes())
        entries.append(dict(path=relative,before_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),
                            after_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    # New helper has no old counterpart; reverting all its imports leaves it unused.
    helper=ROOT/'avatar-2d/service/gesture_planner.py';target=DIRECTORY/'release/avatar-2d/service/gesture_planner.py'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(helper.read_bytes())
    (DIRECTORY/'manifest.json').write_text(json.dumps(dict(files=entries,added_helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest()),indent=2),encoding='utf-8')
    print('Frozen 9 changed source files and gesture helper; rollback excludes credentials, history, memory and clips.')

if __name__=='__main__':main()
