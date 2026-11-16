import hashlib,json,sqlite3,sys,time,urllib.request
from pathlib import Path
ROOT=Path('D:/XiaolinDigitalHuman');STATE=ROOT/'avatar-2d/runtime/qwen-realtime-v2';OUT=ROOT/'deployment/qwen-new-mode-20261110/reports'
with urllib.request.urlopen('http://127.0.0.1:8771/api/health',timeout=5) as response:health=json.load(response)
with sqlite3.connect(STATE/'capabilities.sqlite3') as db:
    counts=[list(row) for row in db.execute('SELECT kind,user,COUNT(*) FROM documents GROUP BY kind,user ORDER BY kind,user')]
files={}
for name in ['avatar-2d/service/gesture_planner.py','avatar-2d/models/wav2lip256.pth','avatar-2d/tools/windows_runtime.py']:
    with (ROOT/name).open('rb') as source:files[name]=hashlib.file_digest(source,'sha256').hexdigest()
record=dict(created=time.time(),health=health,counts=counts,existing_file_hashes=files)
name=sys.argv[1];(OUT/(name+'.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
if name=='after-restart':
    before=json.loads((OUT/'before-stop.json').read_text());assert before['health']['settings']==health['settings'] and before['counts']==counts
    assert before['existing_file_hashes']==files
    print(json.dumps(dict(status='PASSED',settings_preserved=True,memory_counts_preserved=True,existing_files_unchanged=True)))
else:print(json.dumps(dict(status='SNAPSHOT_SAVED',name=name)))
