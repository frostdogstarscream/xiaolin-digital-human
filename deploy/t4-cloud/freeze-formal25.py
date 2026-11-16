"""Freeze the current 25 fps deployment before the authorized 50 fps release."""
import datetime,hashlib,json,shutil,sqlite3,subprocess,tarfile
from pathlib import Path
base=Path('/opt/xiaolin');source=base/'evaluations/presenter-v2-1080/avatar-2d'
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');root=base/'baselines'/('formal25-'+stamp);root.mkdir(parents=True,mode=0o700)
def run(*args):return subprocess.check_output(args,text=True).strip()
info=json.loads(run('docker','inspect','xiaolin-qwen-musetalk-v2'))[0]
for name in ('qwen-realtime-v2','presenter-v2-1080'):
 shutil.copytree(source/'experiments'/name,root/'avatar-2d/experiments'/name,ignore=shutil.ignore_patterns('__pycache__'))
private=root/'private';private.mkdir(mode=0o700)
for src,name in [(source/'runtime/qwen-realtime-v2/settings.json','settings.json'),(base/'shared/config/system.conf','system.conf'),(base/'releases/20261110-ports/deployment/nginx.conf','nginx.conf'),(base/'deployment/control-current.sh','control-current.sh'),(Path('/etc/systemd/system/xiaolin.service.d/current-only.conf'),'current-only.conf')]:
 shutil.copy2(src,private/name);(private/name).chmod(0o600)
state=source/'runtime/qwen-realtime-v2/capabilities.sqlite3'
if state.exists():
 with sqlite3.connect(state) as src,sqlite3.connect(private/'capabilities.sqlite3') as dst:src.backup(dst)
(private/'container.json').write_text(json.dumps(info,indent=2));(private/'container.json').chmod(0o600)
shutil.copy2(source/'source-manifest.json',root/'source-manifest.json')
shutil.copy2(source/'assets/presenter-v2-1080/profile.json',root/'profile.json')
asset_files=[]
for p in (source/'runtime/presenter-v2-1080/avatars').rglob('coords.json'):
 asset_files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()})
(root/'asset-references.json').write_text(json.dumps({'original_root':str(source),'files':asset_files,'note':'Existing models and frame caches remain at their original paths.'},indent=2))
run('docker','tag',info['Image'],'xiaolin-formal25-baseline:'+stamp)
with tarfile.open(root/'code.tar.gz','w:gz') as archive:archive.add(root/'avatar-2d',arcname='avatar-2d')
hashes={str(p.relative_to(root)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in root.rglob('*') if p.is_file()}
(root/'sha256.json').write_text(json.dumps(hashes,indent=2));(root/'sha256.json').chmod(0o600)
report={'baseline':str(root),'fps':25,'lipsync_backend':json.loads((private/'settings.json').read_text())['lipsync_backend'],'container':'xiaolin-qwen-musetalk-v2','image_id':info['Image'],'code_sha256':hashes['code.tar.gz'],'database_backup':state.exists()}
(root/'baseline.json').write_text(json.dumps(report,indent=2));(base/'deployment/formal25-baseline.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
