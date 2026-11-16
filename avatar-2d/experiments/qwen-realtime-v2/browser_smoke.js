async page=>{
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected'&&document.querySelector('video').videoWidth===1080,null,{timeout:60000});
  async function ask(text){
    await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(text);
    const start=Date.now();await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    return page.evaluate(start=>{const e=qwenDemo.events;const errors=e.filter(x=>x.type==='error');if(errors.length)throw Error(JSON.stringify(errors));return {text:e.filter(x=>x.type==='assistant_text').at(-1)?.text,capability:e.find(x=>x.type==='capability_result')?.result,gestures:e.filter(x=>x.type==='gesture'),wallMs:Date.now()-start,health:null};},start);
  }
  const welcome=await ask('你好，我第一次来，请欢迎我。');
  if(!welcome.capability?.coordinated)throw Error('Missing real coordination');
  const deadline=Date.now()+15000;
  while(true){const health=await page.evaluate(async()=>await(await fetch('/api/health')).json());if(health.render_stats.motion_frames>=175)break;if(Date.now()>deadline)throw Error('Welcome did not finish 175 frames');await page.waitForTimeout(100);}
  const attendance=await ask('请帮我执行一次上班考勤打卡。');
  if(!attendance.capability?.attendance?.ok||!attendance.text?.includes('占位'))throw Error('Real MCP execution missing '+JSON.stringify(attendance));
  return {status:'PASSED',scope:'public browser real coordinator and registered Fay MCP',welcome,attendance};
}
