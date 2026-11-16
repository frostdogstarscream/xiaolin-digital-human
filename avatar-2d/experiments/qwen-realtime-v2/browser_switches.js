async page=>{
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected',null,{timeout:60000});
  const results={cases:[]};const original=await page.evaluate(()=>api('/api/settings'));
  async function save(values){
    await page.getByRole('button',{name:'模型与能力',exact:true}).click();
    for(const [key,value] of Object.entries(values))await page.locator('#'+key).setChecked(value);
    await page.getByRole('button',{name:'保存并应用',exact:true}).click();
    await page.waitForFunction(()=>!qwenDemo.provider&&document.querySelector('#settings-message').textContent.includes('已保存'),null,{timeout:15000});
    await page.getByRole('button',{name:'对话',exact:true}).click();
  }
  async function ask(text){
    await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(text);await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    return page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e.filter(x=>x.type==='error')));return {text:e.filter(x=>x.type==='assistant_text').at(-1)?.text,capability:e.find(x=>x.type==='capability_result')?.result,gestures:e.filter(x=>x.type==='gesture')};});
  }
  try{
    await save({coordinator_enabled:true,mcp_enabled:false,knowledge_enabled:false,memory_enabled:false,gestures_enabled:true});
    const disabled=await ask('请帮我执行一次上班考勤打卡。');
    if(disabled.capability?.attendance?.executed)throw Error('Disabled MCP executed');results.cases.push({name:'mcp_off',...disabled});
    const quote=await ask('“再见”是什么意思？');
    if(quote.capability?.gesture==='goodbye-wave')throw Error('Quoted farewell triggered goodbye');results.cases.push({name:'quoted_goodbye',...quote});
    const noMotion=await ask('不要做动作，请解释一下展馆的用途。');
    if((noMotion.capability&&noMotion.capability.gesture!=='idle')||noMotion.gestures.length)throw Error('No-motion request ignored');results.cases.push({name:'explicit_no_motion',...noMotion});
    await save({coordinator_enabled:false,mcp_enabled:true,knowledge_enabled:true,memory_enabled:true,gestures_enabled:true});
    const before=await page.evaluate(async()=>await api('/api/capabilities'));
    const master=await ask('请记住我的验收编号是橙鹿九三，并执行上班打卡，再挥手欢迎我。');
    const after=await page.evaluate(async()=>await api('/api/capabilities'));
    if(master.capability||master.gestures.length||(after.counts.memory||0)!==(before.counts.memory||0))throw Error('Master switch failed');
    results.cases.push({name:'master_off_all_gates',...master,memoryBefore:before.counts.memory,memoryAfter:after.counts.memory});
    results.status='PASSED';return results;
  }finally{
    await page.evaluate(original=>{const {revision,...value}=original;return api('/api/settings',{method:'POST',body:JSON.stringify(value)});},original);
  }
}
