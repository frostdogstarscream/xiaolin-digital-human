async page=>{
  const results={scope:'authenticated public Chrome; frozen audio, not physical microphone',cases:[]};
  await page.waitForFunction(()=>qwenDemo.pc?.connectionState==='connected'&&document.querySelector('video').videoWidth===1080,null,{timeout:60000});
  async function ask(text){
    await page.evaluate(()=>{qwenDemo.events=[];});
    await page.getByRole('textbox',{name:'输入问题'}).fill(text);
    const began=Date.now();await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playing'),null,{timeout:30000});
    const firstPlayWallMs=Date.now()-began;
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done'),null,{timeout:45000});
    return await page.evaluate(firstPlayWallMs=>{
      const e=qwenDemo.events;const reply=e.filter(x=>x.type==='assistant_text').at(-1);const done=e.filter(x=>x.type==='response_done').at(-1);
      if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e.filter(x=>x.type==='error')));
      if(!reply?.text||done?.status!=='completed')throw Error('No complete spoken response');
      return {text:reply.text,inputToPcmMs:done.input_to_pcm_ms,pcmToPlayMs:e.find(x=>x.type==='playing')?.pcm_to_play_ms,firstPlayWallMs};
    },firstPlayWallMs);
  }
  results.cases.push({name:'text_question_and_native_lipsync',...await ask('请用一句话介绍你自己，不超过二十个字。')});
  await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='qwen-frozen-input';input.hidden=true;document.body.append(input);});
  await page.locator('#qwen-frozen-input').setInputFiles('D:/Code/3D数字人/attendance-mcp/runtime/voice-input.wav');
  const upload=await page.evaluate(async()=>{
    const input=document.querySelector('#qwen-frozen-input');const wav=await input.files[0].arrayBuffer();input.remove();
    const view=new DataView(wav);let offset=12,data,rate,channels,bits;
    const tag=i=>String.fromCharCode(...new Uint8Array(wav,i,4));
    while(offset+8<=view.byteLength){const name=tag(offset),length=view.getUint32(offset+4,true);if(name==='fmt '){channels=view.getUint16(offset+10,true);rate=view.getUint32(offset+12,true);bits=view.getUint16(offset+22,true);}if(name==='data'){data=new Uint8Array(wav,offset+8,length);break;}offset+=8+length+(length%2);}
    if(!data||rate!==16000||channels!==1||bits!==16)throw Error('Unexpected fixture format');
    qwenDemo.events=[];const began=performance.now();const chunks=[];
    for(let i=0;i<data.length;i+=3200)chunks.push(data.slice(i,i+3200));
    for(let i=0;i<10;i++)chunks.push(new Uint8Array(3200));
    for(let i=0;i<chunks.length;i++){qwenDemo.ws.send(chunks[i]);await new Promise(r=>setTimeout(r,Math.max(0,began+(i+1)*100-performance.now())));}
    return {rate,channels,bits,bytes:data.length};
  });
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='user_text')&&qwenDemo.events.some(e=>e.type==='playback_done'),null,{timeout:45000});
  results.cases.push(await page.evaluate(upload=>{
    const e=qwenDemo.events;const user=e.find(x=>x.type==='user_text')?.text;const answer=e.filter(x=>x.type==='assistant_text').at(-1)?.text;
    if(!user?.includes('打卡')||!answer||e.some(x=>x.type==='error'))throw Error('Frozen realtime speech failed: '+JSON.stringify(e));
    return {name:'frozen_pcm_speech_to_speech',...upload,recognized:user,answer};
  },upload));
  await page.evaluate(()=>{qwenDemo.events=[];});
  await page.getByRole('textbox',{name:'输入问题'}).fill('请介绍一下参观展馆时可以注意哪些事情。');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playing'),null,{timeout:30000});
  await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('button',{name:'打断',exact:true}).click();
  await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='interrupted'),null,{timeout:15000});
  const interrupted=await page.evaluate(async()=>{const health=await(await fetch('/api/health')).json();if(health.audio_queue!==0||health.render_error)throw Error('Interrupt did not clear queue');return {name:'interrupt',audioQueue:health.audio_queue,rtc:health.rtc_connected};});
  results.cases.push(interrupted);
  results.cases.push({name:'answer_after_interrupt',...await ask('请只回复：打断后已恢复。')});
  await page.getByRole('button',{name:'停止对话',exact:true}).click();
  await page.waitForFunction(()=>!qwenDemo.provider,null,{timeout:10000});
  results.media=await page.evaluate(async()=>{const pc=qwenDemo.pc,s=await pc.getStats(),v=document.querySelector('video');const video=[...s.values()].find(x=>x.type==='inbound-rtp'&&x.kind==='video');const audio=[...s.values()].find(x=>x.type==='inbound-rtp'&&x.kind==='audio');return {connection:pc.connectionState,width:v.videoWidth,height:v.videoHeight,videoFrames:video?.framesDecoded,audioBytes:audio?.bytesReceived,micBytes:(await(await fetch('/api/health')).json()).mic_bytes};});
  if(results.media.width!==1080||results.media.height!==1920||!results.media.audioBytes)throw Error('Real media evidence missing');
  results.status='PASSED';return results;
}
