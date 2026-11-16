"""Exercise real v2 scheduling methods without loading a second GPU model."""
import ast,json,threading,unittest,queue
from pathlib import Path
from types import SimpleNamespace
source=ast.parse((Path(__file__).parent/'live_engine_v2.py').read_text(encoding='utf-8'))
node=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Presenter')
node.bases=[ast.Name(id='object',ctx=ast.Load())];node.body=[n for n in node.body if not(isinstance(n,ast.FunctionDef) and n.name=='__init__')]
def clear_queue(q):
    while not q.empty():q.get_nowait()
scope={'base':SimpleNamespace(clear_queue=clear_queue)};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'real-v2-scheduler','exec'),scope)
Presenter=scope['Presenter']
class Scheduler(unittest.TestCase):
    def setup_presenter(self):
        p=Presenter();p.lock=threading.Lock();p.motion=None;p.motion_requested=None;p.motion_index=0;p.idle_index=0;p.pose=('idle',0)
        p.assets=SimpleNamespace(clips={name:(None,[None]*count) for name,count in [('idle',750),('welcome-wave',175),('goodbye-wave',175),('explain-open-palms',175),('acknowledge-nod',100)]})
        p.stats=dict(last_motion=None,motion_frames=0,idle_frames=0,idle_loops=0);return p
    def prepare_reset(self,p):
        p.generation=0;p.reset_requested=threading.Event();p.preserve_motion_on_reset=False;p.pending_audio=[1]
        p.asr=SimpleNamespace(queue=queue.Queue());p.asr.queue.put(1);p.output=SimpleNamespace()
    def test_idle_runs_forward_and_wraps_once(self):
        p=self.setup_presenter();frames=[p._advance([]) for _ in range(753)]
        self.assertEqual([i for _,i in frames],list(range(750))+[0,1,2]);self.assertEqual(p.stats['idle_loops'],1)
    def test_each_action_plays_all_frames_then_returns_to_idle(self):
        for action,count in [('welcome-wave',175),('goodbye-wave',175),('explain-open-palms',175),('acknowledge-nod',100)]:
            p=self.setup_presenter();p.request_motion(action);frames=[p._advance([]) for _ in range(count+2)]
            self.assertEqual(frames[:count],[(action,i) for i in range(count)]);self.assertEqual(frames[count:],[('idle',0),('idle',1)])
    def test_audio_chunks_without_start_do_not_restart_motion(self):
        p=self.setup_presenter();packet=SimpleNamespace(userdata={'status':'start','action':'welcome-wave'})
        self.assertEqual(p._advance([packet]),('welcome-wave',0))
        self.assertEqual(p._advance([SimpleNamespace(userdata={'action':'welcome-wave'})]),('welcome-wave',1))
    def test_idle_request_cannot_become_a_non_looping_motion(self):
        p=self.setup_presenter()
        with self.assertRaises(ValueError):p.request_motion('idle')
    def test_new_question_preserves_idle_phase_but_clears_old_audio(self):
        p=self.setup_presenter();self.prepare_reset(p)
        for _ in range(123):p._advance([])
        p.flush_talk();self.assertEqual(p._advance([]),('idle',123))
        self.assertEqual(p.generation,1);self.assertTrue(p.asr.queue.empty());self.assertFalse(p.pending_audio)
    def test_interrupt_cancels_motion_and_returns_to_idle(self):
        p=self.setup_presenter();self.prepare_reset(p);p.request_motion('welcome-wave');p._advance([])
        p.flush_talk();self.assertEqual(p._advance([]),('idle',0));self.assertIsNone(p.motion)
    def test_internal_welcome_to_question_transition_preserves_motion(self):
        p=self.setup_presenter();self.prepare_reset(p);p.request_motion('welcome-wave');p._advance([])
        p.flush_talk(preserve_motion=True);self.assertEqual(p._advance([]),('welcome-wave',1))
if __name__=='__main__':unittest.main(verbosity=2)
