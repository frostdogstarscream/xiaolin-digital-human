async page=>{
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected',null,{timeout:60000});
  const settings=await page.evaluate(()=>api('/api/settings'));
  await page.evaluate(settings=>{const {revision,...s}=settings;return api('/api/settings',{method:'POST',body:JSON.stringify({...s,coordinator_enabled:true,mcp_enabled:true,knowledge_enabled:false,memory_enabled:false,gestures_enabled:false})});},settings);
  const cases=[];
  for(const question of ['不要帮我打卡。','我已经完成上班打卡了。','考勤打卡是什么意思？','别人说“我要打卡”，这句话是什么含义？请不要替任何人执行。','我想在展馆拍照打卡，有什么建议？']){
    await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(question);await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    const result=await page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e.filter(x=>x.type==='error')));return {answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result};});
    if(result.result?.attendance?.executed)throw Error('Negative intent executed MCP '+JSON.stringify({question,result}));cases.push({question,...result});
  }
  return {status:'PASSED',scope:'semantic exclusions; real Qwen, no frontend keyword trigger',cases};
}
