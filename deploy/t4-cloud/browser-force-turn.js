async (page) => {
  await page.unroute('**/api/rtc-config');
  await page.addInitScript(() => {
    const NativePeerConnection = window.RTCPeerConnection;
    window.RTCPeerConnection = class extends NativePeerConnection {
      constructor(configuration) { super({...configuration, iceTransportPolicy:'relay'}); }
    };
  });
  await page.reload();
  await page.waitForFunction(() => typeof pc !== 'undefined' && pc?.connectionState === 'connected', null, {timeout:90000});
  await page.waitForFunction(async () => {
    const stats=await pc.getStats();
    const transport=[...stats.values()].find(s=>s.type==='transport'&&s.selectedCandidatePairId);
    const pair=transport&&stats.get(transport.selectedCandidatePairId);
    const local=pair&&stats.get(pair.localCandidateId);
    return local && (local.candidateType==='relay' || !!local.relayProtocol);
  }, null, {timeout:30000});
  const result = await page.evaluate(async () => {
    const stats = await pc.getStats();
    const transport = [...stats.values()].find(s => s.type === 'transport' && s.selectedCandidatePairId);
    const pair = transport && stats.get(transport.selectedCandidatePairId);
    const candidate = pair && stats.get(pair.localCandidateId);
    return {connection:pc.connectionState, localCandidateType:candidate?.candidateType,
      relayProtocol:candidate?.relayProtocol, policy:pc.getConfiguration().iceTransportPolicy,
      videoWidth:document.querySelector('#player').videoWidth};
  });
  if (result.policy!=='relay' || (result.localCandidateType!=='relay'&&!result.relayProtocol)) throw Error('Forced TURN evidence was not available');
  return result;
}
