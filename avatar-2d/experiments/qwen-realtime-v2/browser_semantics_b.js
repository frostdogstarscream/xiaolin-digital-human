async page=>{
  async function ask(question){
    await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(question);await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    return page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e.filter(x=>x.type==='error')));return {answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result};});
  }
  const vague=await ask('我到公司了。');if(vague.result?.attendance?.executed)throw Error('Ambiguous arrival executed attendance');
  const clarify=await ask('请先问我是否需要执行上班考勤打卡，这一轮不要执行。');if(clarify.result?.attendance?.executed)throw Error('Clarification request executed attendance');
  const confirmation=await ask('需要，帮我办一下。');if(!confirmation.result?.attendance?.ok)throw Error('Contextual confirmation did not execute real MCP '+JSON.stringify(confirmation));
  await page.getByRole('button',{name:'停止对话',exact:true}).click();await page.waitForFunction(()=>!qwenDemo.provider,null,{timeout:10000});
  const plainYes=await ask('好的。');if(plainYes.result?.attendance?.executed)throw Error('Yes without context executed attendance');
  await page.evaluate(async()=>{const s=await api('/api/settings');delete s.revision;for(const key of ['coordinator_enabled','mcp_enabled','knowledge_enabled','memory_enabled','gestures_enabled'])s[key]=true;return api('/api/settings',{method:'POST',body:JSON.stringify(s)});});
  return {status:'PASSED',vague,clarify,confirmation,plainYes};
}
