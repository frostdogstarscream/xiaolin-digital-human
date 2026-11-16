async page=>{
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected'&&document.querySelector('video').videoWidth===1080,null,{timeout:60000});
  await page.evaluate(()=>{qwenDemo.events=[];});
  try{
    await page.getByRole('button',{name:'开启实时对话',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.mic?.context.sampleRate===16000,null,{timeout:15000});
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='user_text'&&e.text.includes('打卡'))&&qwenDemo.events.some(e=>e.type==='playback_done'),null,{timeout:12000});
    return await page.evaluate(async()=>{
      const health=await(await fetch('/api/health')).json();const events=qwenDemo.events;
      if(health.mic_bytes<32000||events.some(e=>e.type==='error'))throw Error('Microphone PCM delivery failed');
      return {status:'PASSED',scope:'Chrome fake microphone using frozen file, not physical microphone',
        sampleRate:qwenDemo.mic.context.sampleRate,micBytes:health.mic_bytes,
        recognized:events.find(e=>e.type==='user_text')?.text,answer:events.filter(e=>e.type==='assistant_text').at(-1)?.text,
        width:document.querySelector('video').videoWidth,height:document.querySelector('video').videoHeight};
    });
  }finally{
    await page.evaluate(async()=>{await stopMic();if(qwenDemo.ws?.readyState===WebSocket.OPEN)send({type:'stop'});});
  }
}
