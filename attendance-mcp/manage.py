"""Idempotent native Fay MCP registration; public output never includes credentials."""
import argparse
import json
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:5010/api/mcp'
URL='http://127.0.0.1:8783/sse'
NAME='小霖 · 占位打卡测试'
TOOL='attendance_check_in'

def manage(enable):
    with requests.Session() as http:
        http.trust_env=False
        def request(method,path,body=None):
            response=http.request(method,BASE+path,json=body,timeout=(3,35));response.raise_for_status();return response.json()
        servers=request('GET','/servers')
        matches=[s for s in servers if s.get('name')==NAME and s.get('ip')==URL and s.get('transport','sse')=='sse']
        if len(matches)>1:raise RuntimeError('Duplicate placeholder registrations; no configuration changed')
        if not matches:
            if not enable:
                target=ROOT/'runtime/registration.json'
                if target.exists():
                    marker=json.loads(target.read_text(encoding='utf-8-sig'));marker['enabled']=False
                    target.write_text(json.dumps(marker,ensure_ascii=False,indent=2),encoding='utf-8')
                return {'enabled':False,'registered':False}
            value=request('POST','/servers',dict(name=NAME,ip=URL,transport='sse',auto_connect=True,autostart=True))
            server=value['server']
        else:server=matches[0]
        sid=int(server['id'])
        if enable:
            request('POST',f'/servers/{sid}/connect',{})
            tools=request('GET',f'/servers/{sid}/tools')
            # Native endpoint returns a tools field in current Fay builds.
            items=tools if isinstance(tools,list) else tools.get('tools',[])
            assert any(t.get('name')==TOOL for t in items),'Placeholder tool discovery failed'
            request('POST',f'/servers/{sid}/tools/{TOOL}/toggle',{'enabled':True})
            request('POST',f'/servers/{sid}/tools/{TOOL}/prestart',{'enabled':False})
            marker=dict(server_id=sid,name=NAME,url=URL,tool=TOOL,enabled=True,prestart=False)
            (ROOT/'runtime').mkdir(parents=True,exist_ok=True)
            target=ROOT/'runtime/registration.json';temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps(marker,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
        else:
            request('POST',f'/servers/{sid}/tools/{TOOL}/toggle',{'enabled':False})
            request('POST',f'/servers/{sid}/disconnect',{})
            marker=dict(server_id=sid,url=URL,tool=TOOL,enabled=False,prestart=False)
            target=ROOT/'runtime/registration.json'
            if target.exists():target.write_text(json.dumps(marker,indent=2),encoding='utf-8')
        return marker

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--disable',action='store_true');args=parser.parse_args()
    print(json.dumps(manage(not args.disable),ensure_ascii=True))
