"""Capture final code/image identity without including shared confidential data."""
import hashlib,json,platform,subprocess,time
from pathlib import Path
base=Path('/opt/xiaolin');release=(base/'current').resolve();deployment=base/'deployment'
original=json.loads((deployment/'application-manifest.json').read_text())
files={item['path']:item for item in original['files']}
for path in (release/'deployment').iterdir():
    if path.is_file() and (path.suffix in ('.py','.sh','.yaml','.conf','.service') or path.name=='ports.json'):
        relative=path.relative_to(release).as_posix()
        files.setdefault(relative,{'path':relative})
actual=[];changes=[]
for relative,item in sorted(files.items()):
    path=release/relative
    assert path.is_file() and not path.is_symlink(),relative
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    actual.append(dict(path=relative,bytes=path.stat().st_size,sha256=digest))
    if item.get('sha256') and item['sha256']!=digest:changes.append(relative)
images=[]
for tag in [f'xiaolin-{component}:{release.name}' for component in ('presenter','fay','asr','turn')]+['nginx:1.28-alpine']:
    data=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
    images.append(dict(tag=tag,id=data['Id'],repo_digests=data.get('RepoDigests'),bytes=data['Size']))
report=dict(version=release.name,release=str(release),generated_at=time.time(),kernel=platform.release(),
    files=actual,cloud_followup_changes=changes,images=images,
    assets_receipt_sha256=hashlib.sha256((deployment/'verified-assets.json').read_bytes()).hexdigest(),
    public_ports={'tcp':[6025,6443,6478],'udp':[6478,'10000-10099']},
    approved_source_cidr='120.195.55.128/28',
    external_acceptance='SEE_CURRENT_ACCEPTANCE_REPORT')
report['host_control_files']=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    for p in [deployment/'control.sh',deployment/'configure_runtime.py',deployment/'ssh-portmap.sh',
              Path('/etc/systemd/system/xiaolin.service'),Path('/etc/systemd/system/xiaolin-ssh-portmap.service')] if p.is_file()]
(deployment/'final-manifest.json').write_text(json.dumps(report,indent=2))
print(json.dumps(dict(version=report['version'],files=len(actual),images=len(images),followup_files=changes)))
