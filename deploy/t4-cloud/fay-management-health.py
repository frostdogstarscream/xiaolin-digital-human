from pathlib import Path
import shutil,subprocess
p=Path('/opt/xiaolin/releases/20261110-ports/deployment/healthcheck.py')
backup=p.with_name(p.name+'.before-management-only')
if not backup.exists():shutil.copy2(p,backup)
s=p.read_text();s=s.replace("elif kind=='fay':assert get('http://127.0.0.1:5000/api/get-run-status',b'{}')['status']", "elif kind=='fay':assert get('http://127.0.0.1:5010/api/mcp/servers/online/tools')['success']")
p.write_text(s)
subprocess.run(['docker','exec','xiaolin-fay-1','python','/app/deployment/healthcheck.py','fay'],check=True)
print('MANAGEMENT_READINESS_PASS')
