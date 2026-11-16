from pathlib import Path
import re,shutil
f=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2')
p=f/'demo.js';s=p.read_text();shutil.copy2(p,p.with_suffix('.js.before-firefox-turn-udp'))
old="const config=await responseConfig.json();const pc=demo.pc=new RTCPeerConnection("
new="""const config=await responseConfig.json();
  if(navigator.userAgent.includes('Firefox/')){
    config.iceServers=config.iceServers.map(server=>{
      const urls=Array.isArray(server.urls)?server.urls:[server.urls];
      return {...server,urls:[...new Set(urls.flatMap(url=>url.startsWith('turn:')&&url.includes('transport=tcp')?[url.replace('transport=tcp','transport=udp'),url]:[url]))]};
    });
  }
  const pc=demo.pc=new RTCPeerConnection("""
assert old in s;s=s.replace(old,new);p.write_text(s)
p=f/'index.html';s=re.sub(r'/demo.js\?v=[^"\s]+','/demo.js?v=20261111-firefox-turn4',p.read_text());p.write_text(s)
print('FIREFOX_UDP_AND_TCP_TURN_ENABLED')
