async page=>{
  await page.waitForFunction(()=>window.qwenDemo?.pc?.connectionState==='connected'&&document.querySelector('video').videoWidth===1080,null,{timeout:60000});
  return await page.evaluate(async()=>{
    const d=qwenDemo;const v=document.querySelector('video');const stats=await d.pc.getStats();
    const transport=[...stats.values()].find(x=>x.type==='transport'&&x.selectedCandidatePairId);
    const pair=transport&&stats.get(transport.selectedCandidatePairId);const local=pair&&stats.get(pair.localCandidateId);
    return {status:'PASSED',scope:'actual public Chrome media reception',connection:d.pc.connectionState,width:v.videoWidth,height:v.videoHeight,
      frames:v.getVideoPlaybackQuality().totalVideoFrames,localType:local?.candidateType,relayProtocol:local?.relayProtocol};
  });
}
