"""Freeze explicit experimental copies of render/encoder/acceptance harness."""
from pathlib import Path
import textwrap
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'presenter-v2-1080'

source=(OLD/'engine_baseline.py').read_text(encoding='utf-8')
render=textwrap.dedent(source[source.index('    def render(self, quit_event):'):source.index('\n\ndef options(')])
for a,b in [('self.batch_size*2','self.batch_size'),('packets[i*2:i*2+2]','packets[i:i+1]'),("self.pose = ('welcome-wave', 0)","pass  # Keep last pose for idle segment matching")]:
    assert a in render,a;render=render.replace(a,b)
(HERE/'render50.py').write_text('import numpy as np\nfrom engine_baseline import clear_queue, AudioFrameData\n\n'+render,encoding='utf-8')
encoder=(OLD/'video_encoder.py').read_text(encoding='utf-8').replace('Fraction(25)','Fraction(50)').replace("'4.0'","'4.2'").replace("'40'","'42'").replace("+'28'","+'2a'").replace('4000000','8000000').replace('6000000','12000000')
(HERE/'encoder50.py').write_text(encoder,encoding='utf-8')
test=(OLD/'check_t4_sustained.py').read_text(encoding='utf-8')
test=test.replace('import live_engine_v2 as engine','import engine50 as engine').replace('from video_encoder import configure','from encoder50 import configure')
test=test.replace("'outputs/presenter-v2-1080/t4-sustained'","'outputs/presenter-50fps/t4-sustained'")
test=test.replace('>=24.9','>=49.5').replace("requested_seconds=DURATION,","requested_seconds=DURATION, target_fps=50,")
test=test.replace("precision='FP32'","precision=os.environ.get('XIAOLIN_50_PRECISION','fp32').upper()")
test=test.replace("assets.dtype==torch.float32","assets.dtype==(torch.float16 if os.environ.get('XIAOLIN_50_PRECISION')=='fp16' else torch.float32)")
test=test.replace("report['interrupt']=dict(","report['idle_segment_history']=p.idle_scheduler.history\n        report['idle_plan']=assets.idle_plan\n        report['interrupt']=dict(")
(HERE/'check50.py').write_text(test,encoding='utf-8')
print('Built isolated render50, encoder50, check50')
