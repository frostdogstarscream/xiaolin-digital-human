"""Real MCP handshake and RPC. Only the placeholder is executed."""
import asyncio
import json
import os
import time
from pathlib import Path
os.environ['NO_PROXY']='127.0.0.1,localhost'
from mcp import ClientSession
from mcp.client.sse import sse_client
import requests
ROOT=Path(__file__).resolve().parent

async def main():
    with requests.Session() as http:
        http.trust_env=False;before=http.get('http://127.0.0.1:8783/health',timeout=3).json()
    start=time.perf_counter()
    async with sse_client('http://127.0.0.1:8783/sse',timeout=10) as (read,write):
        async with ClientSession(read,write) as session:
            init=await session.initialize();tools=await session.list_tools()
            assert [t.name for t in tools.tools]==['attendance_check_in']
            tool=tools.tools[0];assert not tool.inputSchema.get('required')
            result=await session.call_tool('attendance_check_in',{})
            assert not result.isError and ''.join(c.text for c in result.content if getattr(c,'type',None)=='text')=='success'
    with requests.Session() as http:
        http.trust_env=False;after=http.get('http://127.0.0.1:8783/health',timeout=3).json()
    assert after['call_count']-before['call_count']==1
    report=dict(status='PASSED',protocol=init.protocolVersion,transport='sse',tool=tool.name,
        schema=tool.inputSchema,result='success',actual_server_calls=1,total_seconds=round(time.perf_counter()-start,3))
    (ROOT/'reports').mkdir(exist_ok=True);(ROOT/'reports/protocol-2026-11-04.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':asyncio.run(main())
