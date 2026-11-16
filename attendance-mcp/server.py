"""Local SSE attendance placeholder. No identity, location or real attendance writes."""
import json
import os
import threading
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'
DESCRIPTION='''占位打卡测试工具。仅当用户明确要求执行考勤打卡、上班签到，或明确确认上一轮打卡提议时调用。
支持同义表达及上下文指代，不要求出现固定词句。不用于查询打卡记录。
否定、不需要、已经完成的陈述、打卡概念咨询、引用示例、旅游或咖啡店探店打卡均不调用。
仅说“我到公司了”等含糊陈述应先澄清；只有真实执行后才能说测试成功。
工具不连接真实考勤系统，不读取身份或位置；每轮最多调用一次。返回 success 表示占位测试已执行成功。'''
mcp=FastMCP('Attendance Placeholder',host='127.0.0.1',port=8783)
LOCK=threading.Lock()
RUN_ID=uuid.uuid4().hex
STARTED=time.time()
COUNT=0

@mcp.tool(name='attendance_check_in',description=DESCRIPTION)
def attendance_check_in() -> str:
    global COUNT
    with LOCK:
        RUNTIME.mkdir(parents=True,exist_ok=True)
        event=dict(event='attendance_check_in',result='success',time=time.time(),run_id=RUN_ID,call_id=uuid.uuid4().hex)
        with (RUNTIME/'calls.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps(event)+'\n')
        print('success',flush=True)
        COUNT+=1
    return 'success'

@mcp.custom_route('/health',methods=['GET'])
async def health(request):
    return JSONResponse(dict(service='attendance-mcp-placeholder',pid=os.getpid(),run_id=RUN_ID,
        started=STARTED,call_count=COUNT,tool='attendance_check_in',transport='sse'))

if __name__=='__main__':mcp.run(transport='sse')
