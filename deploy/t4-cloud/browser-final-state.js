async (page) => {
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){
    const state=await page.evaluate(async()=>{
      const h=await(await fetch('/api/health')).json();const v=await api('voice-state');
      const s=await pc.getStats();const transport=[...s.values()].find(x=>x.type==='transport'&&x.selectedCandidatePairId);
      const pair=transport&&s.get(transport.selectedCandidatePairId);const local=pair&&s.get(pair.localCandidateId);
      return {health:{fay_core:h.fay_core,model_state:h.model_state,rtc_connected:h.rtc_connected,audio_queue:h.audio_queue,
        render_error:h.render_error,active_action:h.active_action,epoch:h.epoch},voice_state:v,
        jobs:h.jobs.filter(j=>j.epoch===h.epoch),secure_context:window.isSecureContext,
        width:document.querySelector('#player').videoWidth,height:document.querySelector('#player').videoHeight,
        policy:pc.getConfiguration().iceTransportPolicy,relay_protocol:local?.relayProtocol,
        frames_decoded:[...s.values()].find(x=>x.type==='inbound-rtp'&&x.kind==='video')?.framesDecoded};
    });
    if(state.health.rtc_connected&&state.width>0&&state.health.audio_queue===0&&!state.health.render_error&&
       !state.voice_state.busy&&state.health.active_action==='idle'&&state.jobs.length&&state.jobs.every(j=>j.status==='ready'&&j.started_at>0)){
      return {status:'PASSED',...state};
    }
    await page.waitForTimeout(250);
  }
  throw Error('Final media and welcome did not finish');
}
