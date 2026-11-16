from pathlib import Path
p=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2/demo.js')
s=p.read_text()
old="    fetch('/api/health?rtc_failure='+encodeURIComponent(JSON.stringify(diagnostic)),{keepalive:true}).catch(()=>{});"
new="""    fetch('/api/health?rtc_failure='+encodeURIComponent(JSON.stringify(diagnostic)),{keepalive:true}).catch(()=>{});
    demo.pc.getStats().then(stats=>{
      const pairs=[...stats.values()].filter(x=>x.type==='candidate-pair').slice(0,4).map(x=>({state:x.state,nominated:x.nominated,requestsSent:x.requestsSent,responsesReceived:x.responsesReceived,requestsReceived:x.requestsReceived,responsesSent:x.responsesSent,localType:stats.get(x.localCandidateId)?.candidateType,relayProtocol:stats.get(x.localCandidateId)?.relayProtocol,remoteType:stats.get(x.remoteCandidateId)?.candidateType}));
      return fetch('/api/health?rtc_pairs='+encodeURIComponent(JSON.stringify(pairs)),{keepalive:true});
    }).catch(()=>{});"""
assert old in s;s=s.replace(old,new);p.write_text(s)
print('PAIR_STATISTICS_ENABLED')
