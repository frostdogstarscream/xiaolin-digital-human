async (page) => {
  const entries=[['idle','自然待机',30],['welcome-wave','迎宾挥手',7],['goodbye-wave','告别挥手',7],['explain-open-palms','右手伸手讲解',7],['acknowledge-nod','轻微点头',4]];
  const results=[];
  for(const mode of ['raw','speech']){
    await page.getByRole('combobox',{name:'查看版本'}).selectOption(mode);
    for(const[id,label,seconds]of entries){
      await page.getByRole('button',{name:label,exact:true}).click();
      const suffix=mode==='raw'?'/prepared/'+id+'.mp4':'/outputs/'+id+'/speaking-1080p.mp4';
      await page.waitForFunction(suffix=>{const v=document.querySelector('#player');return v.currentSrc.endsWith(suffix)&&v.videoWidth===1080&&v.videoHeight===1920&&v.readyState>=2&&v.currentTime>.1;},suffix,{timeout:30000});
      const actual=await page.locator('#player').evaluate(v=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration,loop:v.loop,decodedFrames:v.getVideoPlaybackQuality().totalVideoFrames}));
      const expected=mode==='speech'&&id==='idle'?10:seconds;
      if(Math.abs(actual.duration-expected)>.1||actual.loop!==(id==='idle'))throw Error('Wrong preview '+id);
      results.push({mode,id,...actual});
    }
  }
  await page.getByRole('combobox',{name:'查看版本'}).selectOption('raw');await page.getByRole('button',{name:'自然待机',exact:true}).click();
  return {status:'PASSED',origin:page.url(),cases:results};
}
