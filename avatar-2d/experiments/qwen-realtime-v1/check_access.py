"""Bounded HTTP access checks; credentials remain in the existing private file."""
import json
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[3]
private=ROOT/'runtime/server-4t4/private'
access=json.loads((private/'web-access.json').read_text())
url='https://36.133.88.94:6444'
client=requests.Session();client.verify=str(ROOT/'runtime/server-4t4/delivery/xiaolin-root-ca.crt')
unauthorized=client.get(url+'/api/health',timeout=15).status_code;assert unauthorized==401
client.auth=(access['username'],access['password'])
checks={'unauthenticated_health':unauthorized}
for route in ('/api/say','/api/action'):
    result=client.post(url+route,headers={'Origin':url},json={},timeout=15)
    checks[route]=result.status_code;assert result.status_code==410
result=client.post(url+'/api/offer',headers={'Origin':'https://untrusted.invalid'},json={},timeout=15)
checks['foreign_origin_offer']=result.status_code;assert result.status_code==403
health=client.get(url+'/api/health',timeout=15).json()
assert not any('key' in k.lower() or 'secret' in k.lower() for k in health)
report=dict(status='PASSED',tls_verified=True,checks=checks,public_health=health)
out=ROOT/'avatar-2d/outputs/qwen-realtime-v1/access-report.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(dict(status='PASSED',checks=checks,tls_verified=True)))
