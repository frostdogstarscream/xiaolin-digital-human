"""Cancel an in-flight native planner, then run a new turn; no cloud/model calls."""
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent;FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
for key in ('FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','OPENAI_API_KEY','LANGCHAIN_API_KEY','LANGSMITH_API_KEY','EMBEDDING_API_KEY'):os.environ.pop(key,None)
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false')
sys.path[:0]=[str(ROOT.parent/'avatar-2d/service'),str(FAY)];os.chdir(FAY)
from llm import execution_manager as execution
from llm import nlp_cognitive_stream as ncs
import gesture_planner as gestures
import attendance_policy

def main():
    manager=execution.ExecutionManager();entered=threading.Event();release=threading.Event();old_done=threading.Event();new_done=threading.Event();calls=[]
    class Model:
        def invoke(self,messages):
            entered.set();assert release.wait(8)
            return SimpleNamespace(content='{"action":"tool","tool":"attendance_check_in","args":{}}')
    spec=SimpleNamespace(name='attendance_check_in',description='占位打卡测试',example_args={},
        executor=lambda args,attempt:(calls.append(args) or True,'success',None))
    c=gestures.ActionController();c.begin(1);old_cid='cancel-'+c.controller_id
    gestures.register_request('Avatar2D',old_cid,c.context(1),'帮我签到')
    old=execution.ExecutionState(username='Avatar2D',conversation_id=old_cid,original_request='帮我签到',tool_registry={spec.name:spec})
    def old_callback(state):
        try:ncs._auto_reply_after_execution('Avatar2D',state)
        finally:old_done.set()
    old.on_complete=old_callback
    with patch.object(execution,'_get_llm_instance',return_value=Model()),patch.object(execution,'_manager',manager):
        assert manager.submit(old) and entered.wait(3)
        attendance_policy.cancel_turn('Avatar2D');gestures.invalidate('Avatar2D')
        assert not manager.is_busy('Avatar2D')
        c.begin(2);new_cid='new-'+old_cid;gestures.register_request('Avatar2D',new_cid,c.context(2),'现在帮我签到')
        new=execution.ExecutionState(username='Avatar2D',conversation_id=new_cid,original_request='现在帮我签到',
            tool_registry={spec.name:spec},first_plan={'name':spec.name,'args':{}},on_complete=lambda _:new_done.set())
        assert manager.submit(new) and new_done.wait(3)
        release.set();assert old_done.wait(3)
        assert len(calls)==1 and old.cancel_flag and not old.tool_results
        assert manager.get_state('Avatar2D') is new and new.status==execution.ExecutionStatus.DONE
        assert gestures.is_current('Avatar2D',new_cid)
    report=dict(status='PASSED',old_tool_calls=0,new_tool_calls=1,old_callback_did_not_replace_new_state=True,
        cloud_calls=0,production_history_written=False,production_tts_called=False)
    (ROOT/'reports').mkdir(exist_ok=True);(ROOT/'reports/cancellation-2026-11-04.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
