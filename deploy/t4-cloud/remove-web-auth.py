"""Remove browser Basic Auth from the authorized Xiaolin frontends."""
import datetime,json,subprocess
from pathlib import Path

def run(*args):return subprocess.check_output(args,text=True).strip()
names=['xiaolin-nginx-1','xiaolin-musetalk-https']
changes=[]
for name in names:
    info=json.loads(run('docker','inspect',name))[0]
    mount=next(x for x in info['Mounts'] if x['Destination']=='/etc/nginx/nginx.conf')
    p=Path(mount['Source'])
    assert str(p).startswith('/opt/xiaolin/'),p
    original=p.read_text()
    updated='\n'.join(line for line in original.splitlines() if not line.strip().startswith(('auth_basic ','auth_basic_user_file ')))+'\n'
    changes.append((name,p,original,updated))
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
for name,p,original,updated in changes:
    p.with_name(p.name+'.before-remove-auth-'+stamp).write_text(original)
try:
    for name,p,original,updated in changes:p.write_text(updated)
    for name,p,original,updated in changes:run('docker','exec',name,'nginx','-t')
    for name,p,original,updated in changes:run('docker','exec',name,'nginx','-s','reload')
except Exception:
    for name,p,original,updated in changes:p.write_text(original)
    for name,p,original,updated in changes:subprocess.run(['docker','exec',name,'nginx','-s','reload'])
    raise
print(json.dumps({'removed_browser_auth':True,'ports':[6443,6444,6445],'backups':stamp}))
