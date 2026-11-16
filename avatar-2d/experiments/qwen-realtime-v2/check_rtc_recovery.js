async page=>{
  async function sample(){
    await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected'&&document.querySelector('#avatar').videoWidth>0,null,{timeout:60000});
    return page.evaluate(async()=>{
      const pc=qwenDemo.pc,stats=await pc.getStats();
      const inbound=[...stats.values()].filter(s=>s.type==='inbound-rtp').map(s=>({kind:s.kind,bytesReceived:s.bytesReceived,framesDecoded:s.framesDecoded,frameWidth:s.frameWidth,frameHeight:s.frameHeight,packetsLost:s.packetsLost}));
      const pair=[...stats.values()].find(s=>s.type==='candidate-pair'&&s.nominated&&s.state==='succeeded');
      const local=pair&&stats.get(pair.localCandidateId),remote=pair&&stats.get(pair.remoteCandidateId);
      return {session:qwenDemo.session,state:pc.connectionState,policy:pc.getConfiguration().iceTransportPolicy,inbound,pair:pair?{localType:local?.candidateType,localProtocol:local?.protocol,relayProtocol:local?.relayProtocol,remoteType:remote?.candidateType,remotePort:remote?.port}:null};
    });
  }
  const initial=await sample();
  await page.waitForTimeout(3000);const continued=await sample();
  if(continued.inbound.find(s=>s.kind==='video')?.framesDecoded<=initial.inbound.find(s=>s.kind==='video')?.framesDecoded)throw Error('Video is not advancing');
  // Drop only this test's control link; normal page must recover with TURN-only fallback.
  await page.evaluate(()=>qwenDemo.ws.close());
  await page.waitForFunction(previous=>qwenDemo.session!==previous&&qwenDemo.pc?.connectionState==='connected',initial.session,{timeout:60000});
  const recovered=await sample();
  // Chrome can report a peer-reflexive local candidate for a nominated TURN allocation.
  if(recovered.policy!=='relay'||recovered.pair?.relayProtocol!=='tcp')throw Error('TURN recovery not used '+JSON.stringify(recovered));
  return {status:'PASSED',initial,continued,recovered,scope:'Real HTTPS browser video reception and automatic TURN recovery; no model request'};
}
