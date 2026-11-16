async (page) => {
  await page.locator('#interrupt').click();
  const before=await page.evaluate(async()=>{const h=await(await fetch('/api/health')).json();return h.jobs.map(j=>j.job_id);});
  await page.locator('#text').fill('不要做动作，请只回答：公网问答连接正常。');
  const started=Date.now()/1000;
  await page.evaluate(start=>window.__xiaolinQaStart=start,started);
  await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#answer').textContent.includes('公网问答连接正常'),null,{timeout:90000});
  const firstVisible=Date.now()/1000;
  await page.waitForFunction(async()=>{const h=await(await fetch('/api/health')).json();const jobs=h.jobs.filter(j=>j.epoch===h.epoch&&j.text.includes('公网问答连接正常'));return jobs.length&&jobs.every(j=>j.status==='ready'&&j.started_at>0);},null,{timeout:90000});
  return await page.evaluate(async({before,started,firstVisible})=>{
    const h=await(await fetch('/api/health')).json();const jobs=h.jobs.filter(j=>j.epoch===h.epoch&&j.text.includes('公网问答连接正常'));
    if(!jobs.length||jobs.some(j=>j.status!=='ready'||!j.started_at))throw Error('Speech playback not complete');
    return {status:'PASSED',answer:document.querySelector('#answer').textContent,first_visible_seconds:firstVisible-started,
      first_playback_seconds:Math.min(...jobs.map(j=>j.started_at))-started,jobs,rtc_connected:h.rtc_connected};
  },{before,started,firstVisible});
}
