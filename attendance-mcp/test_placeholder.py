"""Local proof and scheduling tests; no model, production memory or real attendance."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'avatar-2d/service'),str(ROOT/'attendance-mcp')]
import server
import attendance_policy as policy
import gesture_planner as gestures

class Service(unittest.TestCase):
    def test_actual_function_prints_and_returns_success(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'RUNTIME',Path(directory)):
            printed=io.StringIO()
            with contextlib.redirect_stdout(printed):result=server.attendance_check_in()
            self.assertEqual(result,'success');self.assertEqual(printed.getvalue(),'success\n')
            events=[json.loads(line) for line in (Path(directory)/'calls.jsonl').read_text().splitlines()]
            self.assertEqual(len(events),1);self.assertEqual(events[0]['result'],'success')

class Scheduling(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)
        self.marker=self.directory/'runtime/registration.json';self.marker.parent.mkdir()
        self.marker.write_text('{"enabled":true,"server_id":1}')
        self.root_patch=patch.object(policy,'ROOT',self.directory);self.marker_patch=patch.object(policy,'MARKER',self.marker)
        self.root_patch.start();self.marker_patch.start()
        self.controller=gestures.ActionController();self.controller.begin(1);self.cid='attendance-test-'+self.controller.controller_id
        gestures.register_request('Avatar2D',self.cid,self.controller.context(1),'帮我签到')
        self.calls=[]
        self.spec=SimpleNamespace(name=policy.TOOL,executor=lambda args,attempt:(self.calls.append(args) or True,'success',None))
        self.state=SimpleNamespace(username='Avatar2D',conversation_id=self.cid,cancel_flag=False,tool_registry={policy.TOOL:self.spec},first_plan={})
    def tearDown(self):self.marker_patch.stop();self.root_patch.stop();self.temp.cleanup()
    def test_same_turn_executes_exactly_once_and_has_real_receipt(self):
        self.assertEqual(policy.invoke_once(self.state,self.spec,{},0),(True,'success',None))
        self.assertEqual(policy.invoke_once(self.state,self.spec,{},1),(True,'success',None));self.assertEqual(len(self.calls),1)
        self.assertTrue(policy.receipt('Avatar2D',self.cid)['success'])
    def test_cancel_before_call_has_no_effect(self):
        gestures.invalidate('Avatar2D');result=policy.invoke_once(self.state,self.spec,{},0)
        self.assertFalse(result[0]);self.assertFalse(self.calls)
    def test_invalid_arguments_and_wrong_success_payload_are_rejected(self):
        self.assertFalse(policy.invoke_once(self.state,self.spec,{'person':'unneeded'},0)[0]);self.assertFalse(self.calls)
        self.spec.executor=lambda *args:(True,'okay',None)
        self.assertFalse(policy.invoke_once(self.state,self.spec,{},0)[0])
        with patch.object(policy,'available',return_value=True):
            self.assertIn('本轮服务端执行凭据=failed',policy.semantic_instruction('Avatar2D',self.cid))
    def test_failure_is_not_retried_in_same_turn(self):
        def fail(*args):self.calls.append(1);return False,None,'offline'
        self.spec.executor=fail
        self.assertFalse(policy.invoke_once(self.state,self.spec,{},0)[0]);self.assertFalse(policy.invoke_once(self.state,self.spec,{},1)[0])
        self.assertEqual(len(self.calls),1)
    def test_other_clients_and_tools_pass_through(self):
        self.state.username='Other'
        self.assertTrue(policy.invoke_once(self.state,self.spec,{},0)[0]);self.assertTrue(policy.invoke_once(self.state,self.spec,{},1)[0])
        self.assertEqual(len(self.calls),2);self.assertEqual(policy.semantic_instruction('Other',self.cid),'')
    def test_each_new_turn_can_execute_once(self):
        policy.invoke_once(self.state,self.spec,{},0)
        self.controller.begin(2);new='new-'+self.cid;gestures.register_request('Avatar2D',new,self.controller.context(2),'再次签到')
        self.state.conversation_id=new
        self.assertTrue(policy.invoke_once(self.state,self.spec,{},0)[0]);self.assertEqual(len(self.calls),2)
    def test_offline_prompt_never_has_success_receipt(self):
        with patch.object(policy,'available',return_value=False):
            text=policy.semantic_instruction('Avatar2D',self.cid,True)
        self.assertIn('unavailable',text);self.assertIn('not_executed',text)

if __name__=='__main__':unittest.main(verbosity=2)
