async (page) => {
  await page.addInitScript(() => {
    const Native = window.RTCPeerConnection;
    window.RTCPeerConnection = class extends Native {
      constructor(configuration) {
        const iceServers = (configuration.iceServers || []).map(server => ({...server,
          urls:(Array.isArray(server.urls)?server.urls:[server.urls]).filter(url=>url.startsWith('turn:')&&url.includes('transport=tcp'))
        })).filter(server=>server.urls.length);
        super({...configuration,iceServers,iceTransportPolicy:'relay'});
      }
    };
  });
  await page.reload();
  await page.waitForFunction(async()=>{
    if(typeof pc==='undefined'||pc?.connectionState!=='connected')return false;
    const s=await pc.getStats();const v=[...s.values()].find(x=>x.type==='inbound-rtp'&&x.kind==='video');
    return v?.framesDecoded>=50;
  },null,{timeout:90000});
  return await page.evaluate(async()=>{
    const s=await pc.getStats();const t=[...s.values()].find(x=>x.type==='transport'&&x.selectedCandidatePairId);
    const pair=t&&s.get(t.selectedCandidatePairId);const local=pair&&s.get(pair.localCandidateId);
    if(pc.getConfiguration().iceTransportPolicy!=='relay'||local?.relayProtocol!=='tcp')throw Error('TURN TCP evidence missing');
    return {connection:pc.connectionState,policy:'relay',relayProtocol:local.relayProtocol,localType:local.candidateType,
      framesDecoded:[...s.values()].find(x=>x.type==='inbound-rtp'&&x.kind==='video')?.framesDecoded};
  });
}
