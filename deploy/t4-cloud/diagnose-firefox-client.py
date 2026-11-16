from pathlib import Path
import re,shutil
f=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2')
p=f/'demo.js';s=p.read_text();shutil.copy2(p,p.with_suffix('.js.before-client-rtc-diagnostics'))
s=s.replace("function reconnectMedia(reason){\n", """function reconnectMedia(reason){
  if(demo.pc){
    const diagnostic={reason:String(reason).slice(0,240),connection:demo.pc.connectionState,ice:demo.pc.iceConnectionState,gather:demo.pc.iceGatheringState,signaling:demo.pc.signalingState};
    fetch('/api/health?rtc_failure='+encodeURIComponent(JSON.stringify(diagnostic)),{keepalive:true}).catch(()=>{});
  }
""")
p.write_text(s)
p=f/'index.html';s=re.sub(r'/demo.js\?v=[^"\s]+','/demo.js?v=20261111-firefox-diag3',p.read_text());p.write_text(s)
print('CLIENT_DIAGNOSTICS_READY')
