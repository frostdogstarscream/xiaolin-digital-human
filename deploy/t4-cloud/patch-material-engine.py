import json
from pathlib import Path

release = Path(json.loads(Path('/opt/xiaolin/deployment/material-release.json').read_text())['release'])
directory = release / 'avatar-2d/experiments/presenter-50fps'
path = directory / 'engine50.py'
source = path.read_text()
source = source.replace("self.cache=ROOT/'runtime/presenter-50fps'", "self.cache=Path(os.environ.get('XIAOLIN_MATERIAL_CACHE',str(ROOT/'runtime/presenter-50fps')))")
source = source.replace("for item in [self.profile['idle'],*self.profile['actions']]:", "self.transition_plan=json.loads((self.cache/'transition-plan.json').read_text()) if (self.cache/'transition-plan.json').exists() else None\n        items=[self.profile['idle'],*self.profile['actions']]\n        if self.transition_plan:items.append({'id':'transitions'})\n        for item in items:")
source = source.replace("self.stats.update(idle_segment_switches=0,video_fps=50)", """self.stats.update(idle_segment_switches=0,video_fps=50)
        self.transitions=None
        if assets.transition_plan:
            from motion_transitions import MotionTransitions
            self.transitions=MotionTransitions(assets.transition_plan,self.idle_scheduler,{name:len(value[1]) for name,value in assets.clips.items()})
            self.stats.update(material_version=assets.transition_plan['version'],transition_frames=0,actions_completed={name:0 for name in assets.transition_plan['entries']})""")
source = source.replace("self.motion_requested=None;self.pending_audio.clear();base.clear_queue(self.asr.queue)\n            if not preserve_motion:self.motion=None", """self.motion_requested=None;self.pending_audio.clear();base.clear_queue(self.asr.queue)
            if self.transitions:
                if not preserve_motion:self.transitions.cancel_pending()
                self.preserve_motion_on_reset=preserve_motion or bool(self.transitions.action)
                self.motion=self.transitions.action
            elif not preserve_motion:self.motion=None""")
source = source.replace("    def _advance(self,packets):\n", """    def _advance(self,packets):
        if self.transitions:
            from motion_transitions import advance
            with self.lock:return advance(self,packets)
""")
assert 'material_version' in source and 'XIAOLIN_MATERIAL_CACHE' in source
compile(source, str(path), 'exec')
path.write_text(source)
path = directory / 'idle_scheduler.py'
source = path.read_text()
source += """
    def seek(self,index):
        for current,segment in enumerate(self.segments):
            if segment['start']<=index<segment['end']:
                self.current=current;self.index=index;return
        raise ValueError('Idle entry outside the available segments')
"""
compile(source, str(path), 'exec')
path.write_text(source)
gateway = release / 'avatar-2d/experiments/qwen-realtime-v2/gateway50.py'
source = gateway.read_text().replace("profile='presenter-formal-50fps',", "profile='presenter-formal-50fps',material_version=getattr(self.assets,'transition_plan',None).get('version') if getattr(self.assets,'transition_plan',None) else None,")
compile(source, str(gateway), 'exec')
gateway.write_text(source)
print('MATERIAL_ENGINE_PATCHED')
