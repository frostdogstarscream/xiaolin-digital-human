"""Read-only service checks: no model requests, recording, or business writes."""
import asyncio
import importlib
import importlib.metadata
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

import httpx
import websockets
from packaging.requirements import Requirement

ROOT=Path(__file__).resolve().parents[1]


async def check():
    requirements=[]
    for line in (ROOT/'vendor/Fay-source/requirements.txt').read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        req=Requirement(line);version=importlib.metadata.version(req.name)
        assert not req.specifier or version in req.specifier,(req.name,version)
        requirements.append(dict(name=req.name,version=version))
    modules=['flask','pyaudio','azure.cognitiveservices.speech','langchain_openai','langgraph.graph','mcp','chromadb','sentence_transformers','torch']
    for name in modules:importlib.import_module(name)
    endpoints=[]
    async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
        for port,path in [(5000,'/'),(5000,'/static/js/vue.js'),(5000,'/static/css/index.css'),(5010,'/Page3')]:
            response=await client.get('http://127.0.0.1:'+str(port)+path)
            assert response.status_code==200,(port,path,response.status_code)
            assert len(response.content)>100
            endpoints.append(dict(port=port,path=path,status=response.status_code,bytes=len(response.content)))
        response=await client.post('http://127.0.0.1:5000/api/get-run-status')
        assert response.status_code==200
        status=response.json();assert isinstance(status.get('status'),bool)
    sockets=[]
    for port in [10002,10003]:
        async with websockets.connect('ws://127.0.0.1:'+str(port),open_timeout=5,close_timeout=3) as ws:
            pong=await ws.ping();await asyncio.wait_for(pong,5)
            sockets.append(dict(port=port,handshake=True,ping_pong=True))
    report=dict(status='FRAMEWORK_INSTALLED_LOCAL_WEB_AND_WS_VERIFIED',checked_at_utc=datetime.now(timezone.utc).isoformat(),
                python=sys.version.split()[0],executable=sys.executable,requirements=requirements,imports=modules,
                http=endpoints,websockets=sockets,conversation_core_running=status['status'],
                limitations=['No LLM/ASR/TTS/embedding provider credentials configured','No real model or paid API call in installation checks','No LiveTalking or 2D mouth inference installed by this Fay-only task'])
    out=ROOT/'docs/fay-install-validation-20261103.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='requirements'},ensure_ascii=False))
    print('Validated direct requirements:',len(requirements))


if __name__=='__main__':asyncio.run(check())
