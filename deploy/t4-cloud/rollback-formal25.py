"""Restore the frozen 25 fps application and settings, preserving current memory data."""
import hashlib,json,shutil,subprocess
from pathlib import Path
base=Path('/opt/xiaolin');info=json.loads((base/'deployment/formal50-candidate.json').read_text());baseline=Path(info['baseline']);release=Path(info['release'])
for name,expected in json.loads((baseline/'sha256.json').read_text()).items():
 assert hashlib.file_digest((baseline/name).open('rb'),'sha256').hexdigest()==expected,name
settings=base/'evaluations/presenter-v2-1080/avatar-2d/runtime/qwen-realtime-v2/settings.json'
shutil.copy2(settings,release/'settings-before-rollback.json');shutil.copyfile(baseline/'private/settings.json',settings)
def run(*args):return subprocess.check_output(args,text=True).strip()
run('docker','update','--restart=unless-stopped','xiaolin-qwen-musetalk-v2');run('docker','start','xiaolin-qwen-musetalk-v2')
nginx=base/'releases/20261110-ports/deployment/nginx.conf';shutil.copyfile(baseline/'private/nginx.conf',nginx)
run('docker','exec','xiaolin-nginx-1','nginx','-t');run('docker','exec','xiaolin-nginx-1','nginx','-s','reload')
shutil.copyfile(baseline/'private/control-current.sh',base/'deployment/control-current.sh')
run('docker','update','--restart=no','xiaolin-formal-50fps');run('docker','stop','-t','45','xiaolin-formal-50fps')
if (release/'runtime-before.json').exists():shutil.copyfile(release/'runtime-before.json',base/'deployment/current-runtime.json')
print('FROZEN_25FPS_RESTORED; current knowledge/memory database preserved')
