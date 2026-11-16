"""Exercise native ExecutionManager + callback in isolation; --real uses saved models.

Only the read-only probe tool and stream/memory sinks are test doubles. Native
execution/callback code is loaded from the installed Fay source without starting
another Fay core, writing business memory, registering production tools or TTS.
"""
import argparse
import ast
import json
import os
import re
import sys
import threading
import time
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
for name in ('FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','LANGCHAIN_API_KEY','LANGSMITH_API_KEY','OPENAI_API_KEY'):
    os.environ.pop(name,None)
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',ANONYMIZED_TELEMETRY='false')
sys.path[:0]=[str(FAY),str(ROOT/'service')]
os.chdir(FAY)


def main(real, output_name=None, verify_reasoning=False, avatar=False):
    util=types.ModuleType('utils.util');util.log=lambda *args:None
    sys.modules['utils.util']=util
    import llm.execution_manager as native
    from langchain_core.messages import AIMessage,AIMessageChunk,SystemMessage,HumanMessage
    import provider_config
    import gesture_planner

    manager=native.ExecutionManager()
    written=[];calls=[];role_instances=[];finished=threading.Event();entered=threading.Event();release=threading.Event()
    stream=types.ModuleType('core.stream_manager')
    stream.set_current_conversation=lambda *args:None
    stream.set_stop_generation=lambda *args,**kwargs:None
    def write_sentence(username,text,conversation_id):
        written.append(dict(username=username,text=text,conversation_id=conversation_id))
        return True
    stream.write_sentence=write_sentence;stream.new_instance=lambda:stream
    core=types.ModuleType('core');core.__path__=[];core.stream_manager=stream
    sys.modules['core']=core;sys.modules['core.stream_manager']=stream
    state_manager=types.ModuleType('utils.stream_state_manager');state_manager.get_state_manager=lambda:None
    sys.modules['utils.stream_state_manager']=state_manager
    mcp=types.ModuleType('faymcp');mcp.__path__=[]
    runtime=types.ModuleType('faymcp.mcp_runtime');runtime.get_all_resource_texts=lambda:''
    mcp.mcp_runtime=runtime;sys.modules['faymcp']=mcp;sys.modules['faymcp.mcp_runtime']=runtime

    saved_factory=native._get_llm_instance
    class FakeLLM:
        model_name='flash-placeholder'
        default_headers={}
        def invoke(self,*args,**kwargs):return AIMessage(content='{"action":"finish","message":"测试状态码 DUAL_TEST_OK"}')
        def stream(self,*args,**kwargs):
            source='{"gesture":"explain-open-palms","text":"测试通过，状态码为 DUAL_TEST_OK。"}' if avatar else '测试通过，状态码为 DUAL_TEST_OK。'
            for text in source:yield AIMessageChunk(content=text)
    def observed_factory(role='small',streaming=True,session_id=None):
        llm=saved_factory(role,streaming,session_id) if real else FakeLLM()
        role_instances.append(dict(role=role,streaming=streaming,model=llm.model_name,
            session=llm.default_headers.get('x-opencode-session'),reasoning_effort=getattr(llm,'reasoning_effort',None),
            thinking=(getattr(llm,'extra_body',None) or {}).get('thinking')))
        return llm
    native._get_llm_instance=observed_factory
    quiet_thread=type('QuietMemoryThread',(),{'__init__':lambda self,*a,**kw:None,'start':lambda self:None})
    namespace=dict(__name__='llm.nlp_cognitive_stream',json=json,re=re,SystemMessage=SystemMessage,HumanMessage=HumanMessage,
        util=util,avatar_gestures=gesture_planner,_get_llm_instance=observed_factory,get_execution_manager=lambda:manager,MyThread=quiet_thread,
        remember_conversation_thread=lambda *a:None,cfg=native.cfg if real else SimpleNamespace(load_config=lambda:None,big_model_engine='flash-placeholder'))
    source=ast.parse((FAY/'llm/nlp_cognitive_stream.py').read_text(encoding='utf-8-sig'))
    names={'_remove_think_from_text','_strip_json_code_fence','_auto_reply_after_execution','_is_single_model_mode'}
    extracted=ast.Module(body=[node for node in source.body if isinstance(node,ast.FunctionDef) and node.name in names],type_ignores=[])
    exec(compile(extracted,str(FAY/'llm/nlp_cognitive_stream.py'),'exec'),namespace)
    nlp=types.ModuleType('llm.nlp_cognitive_stream');nlp.__dict__.update(namespace);sys.modules['llm.nlp_cognitive_stream']=nlp
    assert not nlp._is_single_model_mode(),'Native mode switch is still single'

    def executor(args,attempts):
        entered.set();assert release.wait(5),'Probe release timeout'
        calls.append(dict(args=args,attempts=attempts,thread=threading.current_thread().name))
        return True,'DUAL_TEST_OK：本地只读测试状态正常。',None
    tool=SimpleNamespace(name='local_status_probe',description='返回本地只读测试状态码，不访问网络或业务数据。',
                         executor=executor,example_args={})
    conversation='dual-test-'+uuid.uuid4().hex
    controller=gesture_planner.ActionController();controller.begin(1)
    if avatar:gesture_planner.register_request('Avatar2D',conversation,controller.context(1))
    state=native.ExecutionState(username='Avatar2D' if avatar else 'collaboration_test',conversation_id=conversation,
        original_request='请读取本地测试状态，并用一句话报告状态码 DUAL_TEST_OK。',
        first_plan={'name':'local_status_probe','args':{}},tool_registry={'local_status_probe':tool})
    callback_errors=[]
    def callback(done):
        try:nlp._auto_reply_after_execution(done.username,done)
        except Exception as exc:callback_errors.append(type(exc).__name__)
        finally:finished.set()
    state.on_complete=callback
    started=time.perf_counter();assert manager.submit(state);submit_ms=(time.perf_counter()-started)*1000
    assert entered.wait(3)
    assert manager.is_busy(state.username)
    duplicate_rejected=not manager.submit(native.ExecutionState(username=state.username))
    assert duplicate_rejected
    release.set()
    assert finished.wait(150),'Background/callback did not finish'
    assert not callback_errors and not state.error
    assert len(calls)==1
    assert calls[0]['thread'].startswith('big-model-exec-')
    assert {x['role'] for x in role_instances}=={'big','small'}
    assert all(x['conversation_id']==conversation for x in written)
    joined=''.join(x['text'] for x in written)
    speech=re.sub(r'<think>[\s\S]*?</think>','',joined)
    assert 'DUAL_TEST_OK' in speech and '_<isend>' in speech
    if avatar:
        signal=gesture_planner.signal('Avatar2D',conversation)
        assert signal['gesture']=='explain-open-palms' and '"gesture"' not in speech and 'explain-open-palms' not in speech
        assert controller.reserve(signal,1)=='explain-open-palms'
    assert manager.get_state(state.username).status==native.ExecutionStatus.IDLE,'Completion was not consumed'
    if real:
        assert len({x['session'] for x in role_instances})==1,'Roles did not share conversation routing'
    if verify_reasoning:
        assert real
        for item in role_instances:
            assert item['model']=='deepseek-v4.1-flash'
            assert item['reasoning_effort']==('medium' if item['role']=='big' else 'low')
            assert item['thinking']=={'type':'enabled' if item['role']=='big' else 'disabled'}
    report=dict(status='NATIVE_DUAL_COLLABORATION_PASSED',real_model_calls=real,cloud_calls=2 if real else 0,
        native_mode='dual',submit_ms=round(submit_ms,3),background_thread=True,one_task_per_user=True,
        tool_calls=len(calls),same_conversation_callback=True,end_marker_written=True,result_consumed=True,
        final_reply=speech.replace('_<isend>','').strip(),roles=[{k:v for k,v in x.items() if k!='session'} for x in role_instances],
        total_seconds=round(time.perf_counter()-started,3),production_tools_registered=False,production_history_written=False,
        production_tts_called=False,scope='Native execution manager and native completion callback; local read-only probe and isolated output sink')
    report['role_reasoning_verified']=verify_reasoning;report['avatar_protocol']=avatar
    path=ROOT/'docs'/(output_name or ('collaboration-real-validation.json' if real else 'collaboration-mock-validation.json'))
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true')
    parser.add_argument('--output');parser.add_argument('--verify-reasoning',action='store_true');parser.add_argument('--avatar',action='store_true');args=parser.parse_args()
    if args.output and (Path(args.output).name!=args.output or not args.output.endswith('.json')):parser.error('Output must be a JSON filename')
    main(args.real,args.output,args.verify_reasoning,args.avatar)
