const $=s=>document.querySelector(s),player=$('#player'),rest=$('#rest');
let clientId=null,socket,epoch=0,mode='chat',playing=null,pending=[],serial=0;
function message(text,error=false){$('#message').textContent=text;$('#message').className='message'+(error?' error':'');}
async function api(path,body={},signal){const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Avatar-Client':'1','X-Avatar-Viewer':clientId||''},body:JSON.stringify(body),signal});if(!response.ok)throw Error(await response.text());return response.json();}
function stopPlayback(){serial++;pending=[];playing=null;player.pause();player.removeAttribute('src');player.load();player.hidden=true;rest.hidden=false;$('#stage-message').textContent='待机';}
function receipt(event,job){if(socket?.readyState===1&&job)socket.send(JSON.stringify({event,job_id:job.job_id}));}
async function next(){
  if(playing||!pending.length)return;const job=pending.shift();if(job.epoch!==epoch){next();return;}
  playing=job;const current=++serial;player.src=job.video;player.muted=false;
  try{await player.play();if(current!==serial)return;player.hidden=false;rest.hidden=true;$('#stage-message').textContent='正在播报';receipt('playback_started',job);}
  catch{message('请点击人物画面允许播放声音。',true);}
}
function enableAudio(){player.muted=false;return playing?player.play().then(()=>{player.hidden=false;rest.hidden=true;receipt('playback_started',playing);}).catch(()=>{}):Promise.resolve();}
async function ensureDisplay(){
  if(!clientId){message('正在连接本机数字人，请稍候。',true);return false;}
  const h=await health();if(h?.model_state!=='ready'){message('LiteAvatar 模型还在加载，请稍候。',true);return false;}
  await api('claim');return true;
}
player.onended=()=>{const job=playing;playing=null;receipt('playback_ended',job);player.hidden=true;rest.hidden=false;$('#stage-message').textContent='待机';next();};
player.onerror=()=>{if(playing){receipt('playback_error',playing);playing=null;message('视频播放失败，请重新提交。',true);next();}};
$('#stage').onclick=enableAudio;
function connect(){
  socket=new WebSocket('ws://'+location.host+'/ws');
  socket.onmessage=({data})=>{
    const e=JSON.parse(data);
    if(e.event==='state'){clientId=e.client_id;epoch=e.epoch;health();return;}
    if(e.event==='playback_owner_changed'&&e.playback_owner!==clientId){stopPlayback();if(typeof cancelMicrophone==='function')cancelMicrophone();message('展示已切换到另一个实验版窗口。');return;}
    if(e.epoch<epoch)return;
    if(e.epoch!==epoch||e.event==='interrupted'){epoch=e.epoch;stopPlayback();}
    if(e.event==='queued'){if(typeof pauseWakeForOutput==='function')pauseWakeForOutput();message('语音已生成，正在排入口型队列。');}
    if(e.event==='rendering'){message('LiteAvatar 正在生成本段口型…');$('#stage-message').textContent='口型生成中';}
    if(e.event==='ready'&&e.playback_owner===clientId){pending.push(e);next();message('口型生成完成。');}
    if(e.event==='answer')$('#answer').textContent+=e.text;
    if(e.event==='answer_complete')$('#answer').textContent=e.text;
    if(e.event==='error')message(e.message,true);
  };
  socket.onclose=()=>{clientId=null;stopPlayback();if(typeof cancelMicrophone==='function')cancelMicrophone();message('服务连接中…');setTimeout(connect,1500);};
}
async function health(){
  try{const h=await(await fetch('/api/health')).json();$('#fay-tag').textContent=h.fay_connected?'Fay 已连接':'Fay 连接中';$('#fay-tag').className='tag '+(h.fay_connected?'ok':'warn');$('#model-tag').textContent=h.model_state==='ready'?'LiteAvatar 已就绪':h.model_state==='error'?'模型加载失败':'人物加载中';$('#model-tag').className='tag '+(h.model_state==='ready'?'ok':'warn');if(clientId&&h.fay_connected&&!h.fay_core)await api('start');if(h.model_state==='ready'&&$('#message').textContent==='正在准备本机服务…')message('服务已就绪，可以输入问题或开启语音唤醒。');return h;}catch{message('无法连接本机实验版服务。',true);}
}
$('#send').onclick=async()=>{try{if(!await ensureDisplay())return;const text=$('#text').value.trim();if(!text)return;stopPlayback();await enableAudio();$('#answer').textContent='';const r=await api(mode,{text});epoch=r.epoch;message(mode==='chat'?'正在等待 Fay 回答…':'正在合成语音…');}catch(e){message(e.message,true);}};
$('#interrupt').onclick=async()=>{stopPlayback();try{epoch=(await api('interrupt')).epoch;}catch(e){message(e.message,true);}};
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>{mode=button.dataset.mode;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('primary',b===button));$('#send').textContent=mode==='chat'?'发送问题':'开始播报';$('#text').maxLength=mode==='chat'?300:240;});
$('#fullscreen').onclick=()=>$('#stage').requestFullscreen().catch(()=>{});
connect();health();setInterval(health,4000);
