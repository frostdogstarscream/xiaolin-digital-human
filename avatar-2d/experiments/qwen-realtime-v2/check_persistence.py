"""Restart only the v2 service; verify persisted settings/data and collect real execution evidence."""
import json,sqlite3,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d')
OUT=ROOT/'outputs/qwen-realtime-v2';STATE=ROOT/'runtime/qwen-realtime-v2'
def get(url):
    with urllib.request.urlopen(url,timeout=4) as response:return json.load(response)
def counts():
    with sqlite3.connect(STATE/'capabilities.sqlite3') as db:
        return [list(row) for row in db.execute('SELECT kind,user,COUNT(*) FROM documents GROUP BY kind,user ORDER BY kind,user')]
before=get('http://127.0.0.1:8771/api/settings');previous=counts()
subprocess.run(['docker','stop','--timeout','25','xiaolin-qwen-realtime-v2'],check=True,capture_output=True)
exit_code=subprocess.check_output(['docker','inspect','xiaolin-qwen-realtime-v2','--format','{{.State.ExitCode}}'],text=True).strip();assert exit_code=='0'
subprocess.run(['docker','start','xiaolin-qwen-realtime-v2'],check=True,capture_output=True)
limit=time.monotonic()+60
while True:
    try:after=get('http://127.0.0.1:8771/api/settings');break
    except Exception:
        if time.monotonic()>limit:raise
        time.sleep(.5)
assert before==after and counts()==previous
mcp=get('http://127.0.0.1:8783/health')
logs=subprocess.check_output(['docker','logs','xiaolin-attendance-1'],stderr=subprocess.DEVNULL,text=True)
evidence=dict(health=mcp,stdout_success_lines=sum(line.strip()=='success' for line in logs.splitlines()),baseline_call_count=2,observed_new_calls=mcp['call_count']-2)
services=subprocess.check_output(['docker','ps','--filter','label=com.docker.compose.project=xiaolin','--format','{{.Names}} {{.Status}}'],text=True)
assert services.count('(healthy)')==6,services
report=dict(status='PASSED',scope='v2 container restart only; no host reboot',exit_code=0,settings=after,settings_preserved=True,document_counts_preserved=True,counts=previous,mcp=evidence,production_services=services.splitlines())
(OUT/'persistence-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
