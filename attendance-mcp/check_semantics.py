"""Saved real models + native judge/executor + real Fay MCP, isolated reply/history sinks."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
for key in ('FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','OPENAI_API_KEY','LANGCHAIN_API_KEY','LANGSMITH_API_KEY','EMBEDDING_API_KEY'):
    os.environ.pop(key,None)
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',NO_PROXY='127.0.0.1,localhost')
sys.path[:0]=[str(ROOT.parent/'avatar-2d/service'),str(FAY)];os.chdir(FAY)
import requests
from langchain_core.messages import SystemMessage,HumanMessage
from llm import nlp_cognitive_stream as ncs
from llm import execution_manager as execution
from faymcp import tool_registry
from fay_llm_runtime import set_session
import gesture_planner as gestures

CASES=[
    ('direct','我要打卡','tool',[]),
    ('synonym','请为我办理上班签到。','tool',[]),
    ('context_confirmation','好的，帮我办一下。','tool',[
        {'role':'user','content':'我准备开始上班了。'},
        {'role':'assistant','content':'现在需要帮你进行占位打卡测试吗？'}]),
    ('standalone_confirmation','好的。','finish',[]),
    ('negative','今天先不打卡，不用帮我签到了。','finish',[]),
    ('already_done','我今天已经打过卡了。','finish',[]),
    ('concept','打卡是什么意思？','finish',[]),
    ('quoted_request','同事说“帮我签到”，这句话是什么意思？','finish',[]),
    ('coffee','这家咖啡店很适合打卡，你觉得呢？','finish',[]),
    ('ambiguous','我到公司了。','finish',[]),
    ('query_records','我今天是否已经打过卡？','finish',[]),
]

def main(output,only=None):
    report=dict(status='RUNNING',cases=[],production_history_written=False,production_tts_called=False,
        scope='Real native judge/execution with actual MCP; isolated context and output')
    with requests.Session() as http:
        http.trust_env=False
        registration=json.loads((ROOT/'runtime/registration.json').read_text(encoding='utf-8'))
        sid=registration['server_id'];response=http.get(f'http://127.0.0.1:5010/api/mcp/servers/{sid}/tools',timeout=5)
        response.raise_for_status();value=response.json();items=value if isinstance(value,list) else value['tools']
        tool_registry.set_server_tools(sid,items,lambda _:True)
        def rpc(server_id,name,args):
            result=http.post(f'http://127.0.0.1:5010/api/mcp/servers/{server_id}/call',json={'method':name,'params':args},timeout=35)
            data=result.json();return bool(data.get('success')),data.get('result') if data.get('success') else data.get('error','MCP call failed')
        ncs.mcp_runtime.call_tool=rpc
        spec=ncs._build_workflow_tool_spec(dict(next(t for t in items if t['name']=='attendance_check_in'),server_id=sid))
        for name,question,expected,history in CASES:
            if only and name not in only:continue
            controller=gestures.ActionController();controller.begin(1);cid='attendance-semantic-'+controller.controller_id
            gestures.register_request('Avatar2D',cid,controller.context(1),question);set_session('Avatar2D',cid)
            state=dict(request=question,messages=[*history,{'role':'user','content':question}],tool_results=[],audit_log=[],context={
                'username':'Avatar2D','avatar_conversation_id':cid,'system_prompt':'你叫小霖，数字讲解员。当前只提供占位打卡测试，不连接真实考勤系统。',
                'tool_registry':{spec.name:spec},'memory_context':'','observation':'','prestart_context':''})
            before=http.get('http://127.0.0.1:8783/health',timeout=3).json()['call_count']
            output_parts=[];hints=[];start=time.perf_counter()
            decision=ncs._call_judge_llm(state,stream_callback=output_parts.append,on_tool_detected=lambda:hints.append(time.perf_counter()-start))
            judge_seconds=time.perf_counter()-start;action=decision.get('action');tool_results=[];final=''.join(output_parts);planning_seconds=None
            if action=='tool':
                task=execution.ExecutionState(username='Avatar2D',conversation_id=cid,original_request=question,
                    messages_buffer=state['messages'],tool_registry={spec.name:spec},first_plan={})
                tool_start=time.perf_counter();execution._big_model_execute(task);planning_seconds=time.perf_counter()-tool_start
                tool_results=task.tool_results
                model=execution._get_llm_instance('small',True,session_id=cid)
                messages=[SystemMessage(content='根据真实工具结果向用户简短反馈，仅说测试结果。工具结果：'+task.final_tool_context+
                    ('；执行失败：'+task.error if task.error else '')),HumanMessage(content=question)]
                final=''.join(gestures.reply_stream(model,messages,'Avatar2D',cid))
            after=http.get('http://127.0.0.1:8783/health',timeout=3).json()['call_count']
            case=dict(case=name,question=question,expected_action=expected,action=action,answer=final,
                actual_server_calls=after-before,judge_seconds=round(judge_seconds,3),
                execution_seconds=round(planning_seconds,3) if planning_seconds is not None else None,
                total_seconds=round(time.perf_counter()-start,3),tool_results=tool_results,
                tool_hints=len(hints),gesture=gestures.signal('Avatar2D',cid)['gesture'])
            case['passed']=action==expected and after-before==(1 if expected=='tool' else 0)
            if expected=='tool':case['passed']=case['passed'] and len(tool_results)==1 and tool_results[0]['success']
            if name=='ambiguous':case['passed']=case['passed'] and ('？' in final or '?' in final) and ('打卡' in final or '签到' in final)
            report['cases'].append(case);report['status']='PASSED' if all(c['passed'] for c in report['cases']) else 'FAILED'
            target=ROOT/'reports'/output;target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(case,ensure_ascii=True),flush=True)
            assert case['passed'],'Semantic or actual tool-call expectation failed: '+name

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='semantics-2026-11-04.json');parser.add_argument('--only',nargs='*');args=parser.parse_args()
    if Path(args.output).name!=args.output:parser.error('Output must be a filename')
    main(args.output,args.only)
