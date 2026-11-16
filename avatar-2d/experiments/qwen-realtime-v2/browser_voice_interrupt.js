async page=>{
  async function ask(text){await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(text);await page.getByRole('button',{name:'发送',exact:true}).click();await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});return page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e));return {answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result};});}
  const preparation=await ask('稍后我会通过语音请你帮我做上班考勤签到，这一轮不要执行，只回答准备好了。');if(preparation.result?.attendance?.executed)throw Error('Preparation executed attendance');
  await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='voice-cap-test';input.hidden=true;document.body.append(input);});
  await page.locator('#voice-cap-test').setInputFiles('D:/Code/3D数字人/attendance-mcp/runtime/voice-input.wav');
  await page.evaluate(async()=>{const i=document.querySelector('#voice-cap-test'),buffer=await i.files[0].arrayBuffer();i.remove();let at=12,data;const view=new DataView(buffer);while(at+8<=buffer.byteLength){const name=String.fromCharCode(...new Uint8Array(buffer,at,4)),n=view.getUint32(at+4,true);if(name==='data'){data=new Uint8Array(buffer,at+8,n);break;}at+=8+n+n%2;}if(!data)throw Error('Missing PCM');qwenDemo.events=[];const began=performance.now();let seq=0;const chunks=[];for(let n=0;n<data.length;n+=3200)chunks.push(data.slice(n,n+3200));for(let n=0;n<10;n++)chunks.push(new Uint8Array(3200));for(const chunk of chunks){qwenDemo.ws.send(chunk);seq++;await new Promise(r=>setTimeout(r,Math.max(0,began+seq*100-performance.now())));}});
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
  const voice=await page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e));return {recognized:e.find(x=>x.type==='user_text')?.text,answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result};});
  if(!voice.result?.attendance?.ok||!voice.recognized?.includes('打卡'))throw Error('Voice to actual MCP failed '+JSON.stringify(voice));
  await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill('请先检索关联记忆，告诉我之前提到的验收代号。');await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='coordinating'),null,{timeout:20000});
  await page.getByRole('button',{name:'打断',exact:true}).click();await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='interrupted'),null,{timeout:15000});
  const recovery=await ask('请只回复：协调打断后恢复正常。');
  if(!recovery.answer?.includes('恢复正常'))throw Error('Post-tool interruption did not recover');
  return {status:'PASSED',scope:'frozen voice to native model -> actual MCP; interrupt during capability coordination',preparation,voice,recovery};
}
