async (page) => {
  await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='xiaolin-asr-fixture';input.hidden=true;document.body.appendChild(input);});
  await page.locator('#xiaolin-asr-fixture').setInputFiles('D:/Code/3D数字人/attendance-mcp/runtime/voice-input.wav');
  return await page.evaluate(async()=>{
    const input=document.querySelector('#xiaolin-asr-fixture');const audio=await input.files[0].arrayBuffer();
    const started=performance.now();const response=await fetch('/api/asr',{method:'POST',
      headers:{'X-Avatar-Client':'1','X-Avatar-Viewer':clientId},body:audio});
    const result=await response.json();input.remove();
    if(!response.ok||!result.text?.includes('打卡'))throw Error('Frozen public ASR failed');
    return {status:'PASSED',scope:'frozen audio through public HTTPS, not physical microphone',
      seconds:(performance.now()-started)/1000,result};
  });
}
