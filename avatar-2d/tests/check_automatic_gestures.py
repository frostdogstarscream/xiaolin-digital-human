"""Protocol and scheduling regression, including native judge/tool compatibility."""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
import gesture_planner as g

class Protocol(unittest.TestCase):
    def decode(self,source,width=1):
        gestures=[];d=g.GestureDecoder(on_gesture=gestures.append)
        emitted=''.join(d.feed(source[i:i+width]) for i in range(0,len(source),width))
        self.assertEqual(emitted,d.finish());return emitted,gestures

    def test_every_boundary_and_unicode(self):
        expected='收到，\n路径 C:\\资料；他说“好”。😀'
        for ascii_ in (True,False):
            raw=json.dumps({'gesture':'acknowledge-nod','text':expected},ensure_ascii=ascii_)
            for split in range(len(raw)+1):
                d=g.GestureDecoder();self.assertEqual(d.feed(raw[:split])+d.feed(raw[split:]),expected);d.finish()
            self.assertEqual(self.decode(raw)[0],expected)

    def test_idle_fallbacks(self):
        for source in ('{"text":"正常正文"}', '{"gesture":"dance","text":"正常正文"}',
                       '{"gesture":{},"text":"正常正文"}','正常正文','```json\n{"text":"正常正文"}\n```'):
            self.assertEqual(self.decode(source),('正常正文',['idle']))

    def test_no_raw_metadata_on_broken_prefix(self):
        for source in ('{"gesture":"bad"}', '{"gesture":','{"gesture":false,"text":123}',
                       '{broken "text":"不能泄露"}', '{"x":"'+'x'*1100):
            d=g.GestureDecoder();self.assertEqual(d.feed(source),'')
            with self.assertRaises(ValueError):d.finish()

    def test_incremental_before_completion(self):
        choices=[];d=g.GestureDecoder(on_gesture=choices.append)
        self.assertEqual(d.feed('{"gesture":"explain-open-palms",'),'')
        self.assertEqual(choices,['explain-open-palms'])
        self.assertEqual(d.feed('"text":"这是一段'), '这是一段')
        self.assertEqual(d.feed('解释。"}'),'解释。')

class Scheduling(unittest.TestCase):
    def setUp(self):self.now=100.;self.c=g.ActionController(lambda:self.now)
    def plan(self,gesture,epoch=1):
        self.c.begin(epoch);return dict(self.c.context(epoch),gesture=gesture,plan_id='p')
    def start(self,p):return self.c.started(dict(p,motion_start=p['gesture']))
    def test_once_and_actual_start_cooldown(self):
        p=self.plan('acknowledge-nod');self.assertEqual(self.c.reserve(p,1),p['gesture'])
        self.assertNotIn(p['gesture'],self.c.last_played)
        self.assertTrue(self.start(p));self.assertFalse(self.start(p))
        self.assertEqual(self.c.reserve(dict(p,gesture='goodbye-wave'),1),'idle')
        q=self.plan('acknowledge-nod',2);self.assertEqual(self.c.reserve(q,2),'idle')
        self.now+=15;q=self.plan('acknowledge-nod',3);self.assertEqual(self.c.reserve(q,3),q['gesture'])
    def test_wake_shared_turn_and_stale_generation(self):
        p=self.plan('welcome-wave');self.c.reserve(p,1);self.start(p)
        context=self.c.context(2);self.assertEqual(context['turn_id'],p['turn_id']);self.assertFalse(context['motion_available'])
        self.assertFalse(self.c.current(p,2));self.assertEqual(self.c.reserve(dict(context,gesture='explain-open-palms',plan_id='q'),2),'idle')
        self.c.cancel();self.assertFalse(self.start(p))
    def test_reception_farewell_timeout_and_reconnect(self):
        p=self.plan('welcome-wave');self.c.reserve(p,1);self.start(p);self.c.cancel()
        self.c.begin(2);self.assertFalse(self.c.context(2)['welcome_allowed'])
        self.now+=60;self.c.begin(3);self.assertTrue(self.c.context(3)['welcome_allowed'])
        q=self.plan('goodbye-wave',4);self.c.reserve(q,4);self.start(q);self.c.begin(5)
        self.assertTrue(self.c.context(5)['welcome_allowed'])
    def test_tool_hint_idle_does_not_spend_slot(self):
        p=self.plan('idle');self.assertEqual(self.c.reserve(p,1),'idle')
        self.assertEqual(self.c.reserve(dict(p,gesture='explain-open-palms'),1),'explain-open-palms')

class Native(unittest.TestCase):
    def setUp(self):
        self.c=g.ActionController();self.c.begin(1);self.cid='unit-'+self.c.controller_id
        g.register_request('Avatar2D',self.cid,self.c.context(1))
    def test_same_request_stream_and_no_metadata(self):
        class Model:
            calls=0
            def stream(m,messages):
                m.calls+=1
                for ch in '{"gesture":"acknowledge-nod","text":"好的，收到。"}':yield SimpleNamespace(content=ch)
        # The real Fay environment supplies langchain_core.
        m=Model();text=''.join(g.reply_stream(m,[],'Avatar2D',self.cid))
        self.assertEqual(text,'好的，收到。');self.assertEqual(m.calls,1)
        self.assertEqual(g.signal('Avatar2D',self.cid)['gesture'],'acknowledge-nod')
    def test_judge_finish_and_tool_preserve_action(self):
        class Model:
            def __init__(m,source):m.source=source
            def stream(m,messages):
                for ch in m.source:yield SimpleNamespace(content=ch)
        output=[]
        d=g.judge_decision(Model('{"action":"finish","gesture":"acknowledge-nod","message":"好\\n的"}'),[],
                           'Avatar2D',self.cid,output.append)
        self.assertEqual(''.join(output),'好\n的');self.assertTrue(d['_streamed'])
        output=[];calls=[]
        d=g.judge_decision(Model('{"action":"tool","gesture":"idle","tool_calls":[{"name":"test","args":{}}]}'),[],
                           'Avatar2D',self.cid,output.append,lambda:calls.append(1))
        self.assertEqual(d['tool_calls'][0]['name'],'test');self.assertFalse(output);self.assertEqual(calls,[1])
    def test_invalidated_background_never_resurrects(self):
        g.invalidate('Avatar2D');self.assertFalse(g.is_current('Avatar2D',self.cid))
        g.register_request('Avatar2D','old',self.c.context(1));self.assertIsNone(g.signal('Avatar2D','old'))
    def test_other_client_passthrough(self):
        class Model:
            def stream(m,messages):yield '原有文本'
        self.assertEqual(list(g.reply_stream(Model(),[],'Other','x')),['原有文本'])

    def test_invalid_body_flags_error_without_second_request(self):
        class Model:
            calls=0
            def stream(m,messages):m.calls+=1;yield SimpleNamespace(content='{"gesture":"welcome-wave"}')
        m=Model()
        with self.assertRaises(ValueError):list(g.reply_stream(m,[],'Avatar2D',self.cid))
        self.assertEqual(m.calls,1);self.assertTrue(g.failed('Avatar2D',self.cid))

    def test_stale_native_callback_exits_before_any_model_or_stream_call(self):
        source=ast.parse((ROOT.parent/'fay-ue4/runtime/fay-local/app/llm/nlp_cognitive_stream.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_auto_reply_after_execution')
        import types
        from unittest.mock import patch
        stream=types.ModuleType('core.stream_manager');stream.new_instance=lambda:SimpleNamespace()
        core=types.ModuleType('core');core.stream_manager=stream
        manager=types.ModuleType('utils.stream_state_manager');manager.get_state_manager=lambda:None
        ns={'avatar_gestures':g};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<native callback>','exec'),ns)
        g.invalidate('Avatar2D')
        with patch.dict(sys.modules,{'core':core,'core.stream_manager':stream,'utils.stream_state_manager':manager}):
            ns['_auto_reply_after_execution']('Avatar2D',SimpleNamespace(conversation_id=self.cid))

    def test_delayed_http_cannot_replace_new_native_turn(self):
        import types
        from unittest.mock import patch
        source=ast.parse((ROOT.parent/'fay-ue4/runtime/fay-local/app/core/fay_core.py').read_text(encoding='utf-8-sig'))
        fn=next(n for c in source.body if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='on_interact')
        switched=[];cleared=[];threads=[]
        sm=SimpleNamespace(set_current_conversation=lambda *args:switched.append(args),
            set_stop_generation=lambda *args,**kwargs:None,clear_Stream_with_audio=lambda *args:cleared.append(args))
        state=types.ModuleType('utils.stream_state_manager');state.get_state_manager=lambda:SimpleNamespace(is_session_active=lambda _:True)
        ns=dict(Interact=object,avatar_gestures=g,stream_manager=SimpleNamespace(new_instance=lambda:sm),
            member_db=SimpleNamespace(new_instance=lambda:SimpleNamespace(is_username_exist=lambda _:'exists')),
            util=SimpleNamespace(log=lambda *args:None),MyThread=lambda **kw:SimpleNamespace(start=lambda:threads.append(kw)))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<native entry>','exec'),ns)
        newer=g.ActionController();newer.begin(2)
        target=SimpleNamespace(**{'__process_interact':lambda _:None})
        new=SimpleNamespace(data={'user':'Avatar2D','msg':'新问题','avatar_context':newer.context(2)},interact_type=1)
        old=SimpleNamespace(data={'user':'Avatar2D','msg':'旧问题','avatar_context':self.c.context(1)},interact_type=1)
        with patch.dict(sys.modules,{'utils.stream_state_manager':state}):
            ns['on_interact'](target,new);self.assertEqual(ns['on_interact'](target,old),'stale')
        self.assertEqual(len(switched),1);self.assertEqual(len(cleared),1);self.assertEqual(len(threads),1)
        self.assertTrue(g.is_current('Avatar2D',new.data['conversation_id']))

    def test_delayed_question_thread_uses_its_original_native_id(self):
        source=ast.parse((ROOT.parent/'fay-ue4/runtime/fay-local/app/llm/nlp_cognitive_stream.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='question')
        ns={'avatar_gestures':g};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<native question>','exec'),ns)
        g.invalidate('Avatar2D')
        self.assertEqual(ns['question']('旧问题','Avatar2D',avatar_conversation_id=self.cid),'')

    def test_stale_turn_never_enters_direct_or_judge_model(self):
        class Model:
            def stream(m,messages):raise AssertionError('Stale turn invoked a model')
        g.invalidate('Avatar2D')
        self.assertEqual(list(g.reply_stream(Model(),[],'Avatar2D',self.cid)),[])
        self.assertEqual(g.judge_decision(Model(),[],'Avatar2D',self.cid,lambda _:None)['message'],'')

    def test_protocol_binds_the_current_request_without_spoken_metadata(self):
        newer=g.ActionController();newer.begin(2);cid='current-'+newer.controller_id
        self.assertTrue(g.register_request('Avatar2D',cid,newer.context(2),'不要动作，只回答：新轮次已生效。'))
        prompt=g.instruction('Avatar2D',cid)
        self.assertIn('本轮最新用户输入',prompt);self.assertIn('新轮次已生效',prompt)
        self.assertNotIn('controller_id',prompt);self.assertNotIn('turn_id',prompt)

class Rendering(unittest.TestCase):
    def test_interrupt_clears_rtc_packets_and_handoff_preserves_body(self):
        tree=ast.parse((ROOT/'service/live_engine.py').read_text(encoding='utf-8'))
        presenter=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Presenter')
        method=next(n for n in presenter.body if isinstance(n,ast.FunctionDef) and n.name=='flush_talk')
        clear=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='clear_queue')
        ns={};exec(compile(ast.Module(body=[clear,method],type_ignores=[]),'<flush>','exec'),ns)
        import queue,threading
        audio=queue.Queue();video=queue.Queue();inputs=queue.Queue()
        p=SimpleNamespace(generation=1,lock=threading.Lock(),reset_requested=threading.Event(),
            motion='welcome-wave',pose=('welcome-wave',99),asr=SimpleNamespace(queue=inputs),
            output=SimpleNamespace(_player=SimpleNamespace(audio=SimpleNamespace(_queue=audio),video=SimpleNamespace(_queue=video))))
        audio.put('old');video.put('old');inputs.put('old');ns['flush_talk'](p,preserve_motion=True)
        self.assertTrue(audio.empty() and video.empty() and inputs.empty());self.assertEqual(p.pose,('welcome-wave',99))
        self.assertEqual(p.motion,'welcome-wave');ns['flush_talk'](p)
        self.assertIsNone(p.motion);self.assertEqual(p.pose,('welcome-wave',0));self.assertEqual(p.generation,3)

    def test_full_clip_once_and_hold_last(self):
        tree=ast.parse((ROOT/'service/live_engine.py').read_text(encoding='utf-8'))
        method=next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='Presenter' for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='_advance')
        ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'<advance>','exec'),ns)
        import threading
        p=SimpleNamespace(assets=SimpleNamespace(clips={'acknowledge-nod':(None,list(range(100)))}),
            motion=None,motion_index=0,stats={'motion_frames':0},lock=threading.Lock(),motion_requested=None,pose=('idle',0))
        packet=SimpleNamespace(userdata={'status':'start','action':'acknowledge-nod','plan_id':'x'})
        self.assertEqual(ns['_advance'](p,[packet]),('acknowledge-nod',0))
        self.assertEqual(packet.userdata['motion_start'],'acknowledge-nod')
        for _ in range(130):ns['_advance'](p,[])
        self.assertEqual(p.stats['motion_frames'],100);self.assertEqual(p.pose,('acknowledge-nod',99));self.assertIsNone(p.motion)

if __name__=='__main__':unittest.main(verbosity=2)
