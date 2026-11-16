async (page) => {
  await page.waitForFunction(() => typeof pc !== 'undefined' && pc?.connectionState === 'connected', null, {timeout: 90000});
  const initial = await page.evaluate(async () => {
    if(window.__xiaolinSampler) clearInterval(window.__xiaolinSampler);
    window.__xiaolinSamples = [];
    window.__xiaolinEvents = [];
    window.__xiaolinSampler = setInterval(async () => {
      if (!pc || pc.connectionState !== 'connected') return;
      const stats = await pc.getStats();
      const video = [...stats.values()].find(s => s.type === 'inbound-rtp' && s.kind === 'video');
      const audio = [...stats.values()].find(s => s.type === 'inbound-rtp' && s.kind === 'audio');
      const transport = [...stats.values()].find(s => s.type === 'transport' && s.selectedCandidatePairId);
      const pair = transport && stats.get(transport.selectedCandidatePairId);
      const local = pair && stats.get(pair.localCandidateId);
      const remote = pair && stats.get(pair.remoteCandidateId);
      window.__xiaolinSamples.push({time:Date.now()/1000, frames:video?.framesDecoded || 0,
        bytes:video?.bytesReceived || 0, packetsLost:video?.packetsLost || 0,
        jitter:video?.jitter || 0, audioBytes:audio?.bytesReceived || 0,
        localType:local?.candidateType, remoteType:remote?.candidateType,
        localProtocol:local?.protocol, relayProtocol:local?.relayProtocol});
    }, 1000);
    socket.addEventListener('message', event => {
      const data = JSON.parse(event.data);
      if (['answer','answer_complete','action_started','playback_started','playback_ended','error'].includes(data.event)) {
        window.__xiaolinEvents.push({time:Date.now()/1000,event:data.event,text:data.text,action:data.action});
      }
    });
    return {secureContext:window.isSecureContext, microphoneAPI:!!navigator.mediaDevices?.getUserMedia,
      connection:pc.connectionState, videoWidth:document.querySelector('#player').videoWidth,
      videoHeight:document.querySelector('#player').videoHeight};
  });
  return initial;
}
