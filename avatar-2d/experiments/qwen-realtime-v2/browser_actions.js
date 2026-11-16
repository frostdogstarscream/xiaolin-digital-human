async page=>{
  await page.waitForFunction(()=>window.qwenDemo?.pc?.connectionState==='connected',null,{timeout:60000});
  const cases=[];
  for(const [question,gesture,frames] of [
    ['你好，我是新来访者，请挥手欢迎我。','welcome-wave',175],
    ['请自然伸手，向我介绍参观展馆时需要注意的事项。','explain-open-palms',175],
    ['我已经听懂了，请点头确认你收到了。','acknowledge-nod',100],
    ['今天就聊到这里，我要离开了，请挥手告别。','goodbye-wave',175]]){
    const before=await page.evaluate(async()=>{qwenDemo.events=[];return (await(await fetch('/api/health')).json()).render_stats.motion_frames;});
    await page.getByRole('textbox',{name:'输入问题'}).fill(question);await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    const plan=await page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e));return {answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result,started:e.filter(x=>x.type==='gesture').map(x=>x.gesture)};});
    if(plan.result?.gesture!==gesture||plan.started.length!==1||plan.started[0]!==gesture)throw Error('Gesture plan or dedupe failed '+JSON.stringify(plan));
    const limit=Date.now()+15000;let health;
    while(true){health=await page.evaluate(async()=>await(await fetch('/api/health')).json());if(health.active_action==='idle'&&health.render_stats.motion_frames>=before+frames)break;if(Date.now()>limit)throw Error('Gesture did not finish');await page.waitForTimeout(100);}
    const actual=health.render_stats.motion_frames-before;if(actual!==frames)throw Error('Gesture frame count '+actual+' expected '+frames);
    cases.push({question,gesture,frames:actual,...plan});
  }
  return {status:'PASSED',scope:'model selected and natively played all four complete actions; no manual action API',cases};
}
