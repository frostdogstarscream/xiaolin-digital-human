from pathlib import Path
import shutil,re
folder=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2')
p=folder/'demo.js';s=p.read_text();shutil.copy2(p,p.with_suffix('.js.before-complete-gather'))
s=s.replace("if(pc.iceGatheringState!=='complete'&&!pc.localDescription.sdp.includes(' typ relay '))", "if(pc.iceGatheringState!=='complete')")
s=s.replace("const candidate=event=>{if(event.candidate?.type==='relay')complete();};", "const candidate=event=>{if(event.candidate===null)complete();};")
s=s.replace('}},12000);','}},20000);')
p.write_text(s)
p=folder/'index.html';s=p.read_text();s=re.sub(r'/demo.js\?v=[^"\s]+','/demo.js?v=20261111-firefox-complete2',s);p.write_text(s)
print('COMPLETE_GATHER_DEPLOYED')
