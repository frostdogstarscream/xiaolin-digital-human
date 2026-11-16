async page=>{
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected'&&document.querySelector('video').videoWidth===1080,null,{timeout:60000});
  await page.getByRole('textbox',{name:'输入问题'}).fill('请用六十个字介绍展馆参观注意事项。');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playing'),null,{timeout:30000});
  const old=await page.evaluate(()=>qwenDemo.events.filter(e=>e.type==='playing').at(-1).response_id);
  await page.evaluate(()=>{const i=document.createElement('input');i.type='file';i.id='barge-file';i.hidden=true;document.body.append(i);});
  await page.locator('#barge-file').setInputFiles('D:/Code/3D数字人/attendance-mcp/runtime/voice-input.wav');
  await page.evaluate(async()=>{
    const i=document.querySelector('#barge-file'),buffer=await i.files[0].arrayBuffer();i.remove();const view=new DataView(buffer);let index=12,raw;
    while(index+8<=buffer.byteLength){const name=String.fromCharCode(...new Uint8Array(buffer,index,4));const length=view.getUint32(index+4,true);if(name==='data'){raw=new Uint8Array(buffer,index+8,length);break;}index+=8+length+length%2;}
    if(!raw)throw Error('Missing frozen PCM');qwenDemo.events=[];const start=performance.now();let count=0;
    for(let at=0;at<raw.length;at+=3200){qwenDemo.ws.send(raw.slice(at,at+3200));count++;await new Promise(r=>setTimeout(r,Math.max(0,start+count*100-performance.now())));}
    for(let n=0;n<10;n++){qwenDemo.ws.send(new Uint8Array(3200));count++;await new Promise(r=>setTimeout(r,Math.max(0,start+count*100-performance.now())));}
  });
  try{
    await page.waitForFunction(old=>qwenDemo.events.some(e=>e.type==='speech_started')&&qwenDemo.events.some(e=>e.type==='playback_done'&&e.response_id!==old),old,{timeout:30000});
    return await page.evaluate(async old=>{
      const events=qwenDemo.events;const start=events.findIndex(e=>e.type==='speech_started');
      if(events.slice(start).some(e=>e.type==='playback_done'&&e.response_id===old))throw Error('Old response completed after speech interruption');
      if(events.some(e=>e.type==='error'))throw Error('Barge-in returned an error');
      const answer=events.filter(e=>e.type==='assistant_text').at(-1);const health=await(await fetch('/api/health')).json();
      return {status:'PASSED',scope:'real-time paced frozen speech interrupts streamed response; not physical microphone',
        oldResponse:old,newResponse:answer?.response_id,recognized:events.find(e=>e.type==='user_text')?.text,
        answer:answer?.text,queue:health.audio_queue,renderError:health.render_error};
    },old);
  }finally{await page.getByRole('button',{name:'停止对话',exact:true}).click();}
}
