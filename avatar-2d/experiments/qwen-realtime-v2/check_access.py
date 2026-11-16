import json
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'avatar-2d/outputs/qwen-realtime-v2'
account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text());url='https://36.133.88.94:6444'
http=requests.Session();http.verify=str(ROOT/'runtime/server-4t4/delivery/xiaolin-root-ca.crt')
checks={};checks['settings_unauthenticated']=http.get(url+'/api/settings',timeout=10).status_code;assert checks['settings_unauthenticated']==401
http.auth=(account['username'],account['password']);before=http.get(url+'/api/settings',timeout=10).json()
checks['foreign_origin_settings']=http.post(url+'/api/settings',headers={'Origin':'https://untrusted.invalid'},json={},timeout=10).status_code;assert checks['foreign_origin_settings']==403
checks['invalid_settings']=http.post(url+'/api/settings',headers={'Origin':url},json={'coordinator_enabled':'false'},timeout=10).status_code;assert checks['invalid_settings']==400
after=http.get(url+'/api/settings',timeout=10).json();assert before==after
checks['data_without_session']=http.get(url+'/api/capabilities',timeout=10).status_code;assert checks['data_without_session']==403
for route in ('say','action'):
    checks[route]=http.post(url+'/api/'+route,headers={'Origin':url},json={},timeout=10).status_code;assert checks[route]==410
report=dict(status='PASSED',tls_verified=True,checks=checks,settings_unchanged=True)
(OUT/'access-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
