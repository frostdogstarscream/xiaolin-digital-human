async (page) => {
  await page.evaluate(async()=>{await api('voice-sleep');window.__wakeResult=await api('voice-input',{text:'小霖小霖'});});
  await page.waitForFunction(async()=>{const h=await(await fetch('/api/health')).json();const v=await api('voice-state');return v.awake&&!v.busy&&h.active_action==='idle'&&h.jobs.some(j=>j.epoch===h.epoch&&j.status==='ready'&&j.text.includes('小霖'));},null,{timeout:90000});
  return await page.evaluate(async()=>{
    const h=await(await fetch('/api/health')).json();const v=await api('voice-state');
    return {status:'PASSED',decision:window.__wakeResult,voice_state:v,jobs:h.jobs.filter(j=>j.epoch===h.epoch),rtc_connected:h.rtc_connected};
  });
}
