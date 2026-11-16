const $ = s => document.querySelector(s), player = $('#player'), rest = $('#rest');
let epoch=0, socket, clientId=null, pc=null, connecting=false, owner=null;
let autoConnectWanted=true,retryTimer=null,retryDelay=1000,connectionAttempt=null,audioUnlocked=false,coreStarting=false,stopConnectionWait=null;
const names={'idle':'待机','welcome-wave':'迎宾挥手','goodbye-wave':'告别挥手','explain-open-palms':'摊手讲解','acknowledge-nod':'点头确认'};
function message(text,error=false){$('#message').textContent=text;$('#message').className='message'+(error?' error':'');}
function badge(id,text,ok){$(id).textContent=text;$(id).className='tag '+(ok?'ok':'warn');}
async function api(path,body={},signal){
  const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Avatar-Client':'1','X-Avatar-Viewer':clientId||''},body:JSON.stringify(body),signal});
  if(!response.ok)throw Error(await response.text());return response.json();
}
function closeDisplay(){if(typeof cancelMicrophone==='function')cancelMicrophone();const stop=stopConnectionWait;stopConnectionWait=null;if(stop)stop();const previous=pc;pc=null;if(previous)previous.close();player.pause();player.srcObject=null;player.hidden=true;rest.hidden=false;}
function retryDisplay(){
  if(!autoConnectWanted||retryTimer||!clientId||socket?.readyState!==1)return;
  retryTimer=setTimeout(()=>{retryTimer=null;display();},retryDelay);
  retryDelay=Math.min(retryDelay*2,10000);
}
function display(){
  if(pc?.connectionState==='connected')return Promise.resolve(true);
  if(connectionAttempt)return connectionAttempt;
  if(!autoConnectWanted||!clientId||socket?.readyState!==1)return Promise.resolve(false);
  clearTimeout(retryTimer);retryTimer=null;
  connectionAttempt=openDisplay().finally(()=>{connectionAttempt=null;});
  return connectionAttempt;
}
async function openDisplay(){
  connecting=true;closeDisplay();message('正在自动连接数字人的画面和声音…');
  badge('#model-tag','音视频连接中',false);
  const connection=new RTCPeerConnection({iceServers:[]});pc=connection;
  const stream=new MediaStream();player.srcObject=stream;player.muted=!audioUnlocked;
  connection.addTransceiver('audio',{direction:'recvonly'});
  connection.addTransceiver('video',{direction:'recvonly'});
  connection.ontrack=e=>{stream.addTrack(e.track);player.play().then(()=>{if(connection===pc){player.hidden=false;rest.hidden=true;}}).catch(()=>{if(connection===pc){player.muted=true;player.play().then(()=>{player.hidden=false;rest.hidden=true;}).catch(()=>{});}});};
  let resolveConnection;
  const connected=new Promise(resolve=>{resolveConnection=resolve;});
  let disconnectTimer;
  const abort=new AbortController();
  const stopWait=()=>{abort.abort();resolveConnection(false);};stopConnectionWait=stopWait;
  const timeout=setTimeout(()=>{abort.abort();resolveConnection(false);},20000);
  let phase='local_offer';
  connection.onconnectionstatechange=()=>{
    if(connection!==pc)return;
    if(connection.connectionState==='connected'){
      clearTimeout(disconnectTimer);retryDelay=1000;resolveConnection(true);
      badge('#model-tag','音视频已连接',true);message('数字人已连接，可以直接录音、问答或播报。');$('#stage-message').textContent='待机';
    }
    if(connection.connectionState==='disconnected'){
      clearTimeout(disconnectTimer);disconnectTimer=setTimeout(()=>{if(connection===pc&&connection.connectionState==='disconnected'){closeDisplay();retryDisplay();}},3000);
    }
    if(['failed','closed'].includes(connection.connectionState)){resolveConnection(false);closeDisplay();message('音视频暂时断开，正在自动重连…');retryDisplay();}
  };
  try{
    await connection.setLocalDescription(await connection.createOffer());
    phase='gathering';
    if(connection.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('本机音视频协商超时')),8000);
      connection.addEventListener('icegatheringstatechange',()=>{if(connection.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});
    });
    phase='server_offer';
    const answer=await api('offer',{sdp:connection.localDescription.sdp,type:connection.localDescription.type},abort.signal);
    if(connection!==pc)return false;
    phase='remote_answer';
    await connection.setRemoteDescription(answer);
    phase='connecting';
    const ready=await connected;
    if(!ready)throw Error('音视频连接尚未完成，将自动重试。');
    return true;
  }catch(e){api('rtc-status',{phase,error:e.name+': '+e.message}).catch(()=>{});if(autoConnectWanted)message('音视频尚未接通，正在自动重试。'+(e.name==='NotSupportedError'?'当前浏览器不支持所选音视频格式。':''));if(connection===pc)closeDisplay();retryDisplay();return false;}
  finally{clearTimeout(timeout);clearTimeout(disconnectTimer);if(stopConnectionWait===stopWait)stopConnectionWait=null;connecting=false;}
}
async function ensureDisplay(){
  autoConnectWanted=true;
  if(pc?.connectionState==='connected')return true;
  message('正在自动连接数字人，请稍候…');
  return await display();
}
function enableAudio(){audioUnlocked=true;player.muted=false;if(!player.srcObject)return Promise.resolve();return player.play().catch(()=>message('请点击人物画面启用声音。',true));}
function connect(){
  socket=new WebSocket('ws://'+location.host+'/ws');
  socket.onmessage=({data})=>{
    const e=JSON.parse(data);
    if(e.event==='state'){clientId=e.client_id;epoch=e.epoch;owner=e.playback_owner;health();return;}
    if(e.event==='playback_owner_changed'){owner=e.playback_owner;if(owner!==clientId){autoConnectWanted=false;clearTimeout(retryTimer);retryTimer=null;closeDisplay();message('另一个窗口正在展示。使用本页的录音或问答功能时会自动切回。');}return;}
    if(e.epoch<epoch)return;epoch=e.epoch;
    if(e.event==='model_ready'&&autoConnectWanted&&!pc)display();
    if(e.event==='interrupted'){$('#stage-message').textContent='待机';message(e.reason==='new_turn'?'正在等待 Fay 生成语音…':'已停止当前语音和动作。');}
    if(e.event==='streaming'){if(typeof pauseWakeForOutput==='function')pauseWakeForOutput();message('Fay 语音已送入实时口型流。');}
    if(e.event==='action_started')$('#action-status').textContent=names[e.action]||'待机';
    if(e.event==='playback_started'){$('#stage-message').textContent=names[e.action]||'正在播报';message('正在实时播报，可随时打断。');}
    if(e.event==='playback_ended'){$('#stage-message').textContent='待机';message('本段播报完成。');}
    if(e.event==='answer')$('#answer').textContent+=e.text;
    if(e.event==='answer_complete')$('#answer').textContent=e.text;
    if(e.event==='error')message(e.message,true);
  };
  socket.onclose=()=>{clientId=null;closeDisplay();if(autoConnectWanted)message('本机服务连接中，将自动恢复…');setTimeout(connect,1500);};
}
async function health(){
  try{
    const h=await(await fetch('/api/health')).json();
    badge('#fay-tag',h.fay_connected?'Fay 已连接':'Fay 未连接',h.fay_connected);
    if($('#action-status'))$('#action-status').textContent=names[h.active_action]||'待机';
    const currentConnected=pc?.connectionState==='connected';
    badge('#model-tag',currentConnected?'音视频已连接':!autoConnectWanted?'另一窗口展示中':h.model_state==='ready'?'音视频连接中':'实时模型准备中',currentConnected);
    badge('#core-state',h.fay_core?'运行中':'未启动',h.fay_core);
    badge('#render-state',h.render_error?'渲染中断':h.model_state==='ready'?'已就绪':'准备中',h.model_state==='ready'&&!h.render_error);
    if($('#provider-name'))$('#provider-name').textContent=h.provider.label||'大模型问答';
    badge('#provider-state',h.provider.configured?(h.dialogue_verified?'问答已通过':'已配置'):'待配置',h.provider.configured);
    if($('#asr-state'))badge('#asr-state',h.asr?.state==='ready'?'本机已就绪':h.asr?.state==='loading'?'加载中':'未就绪',h.asr?.state==='ready');
    if($('#tts-state'))badge('#tts-state',h.speech?.provider==='bailian'?(h.speech.streaming?'百炼流式 · ':'百炼 · ')+(h.speech.voice||'Cherry'):'本机语音',h.speech?.provider==='bailian');
    if($('#tts-voice')&&document.activeElement!==$('#tts-voice')&&h.speech?.voice)$('#tts-voice').value=h.speech.voice;
    $('#start').textContent=h.fay_core?'Fay 核心已运行':'启动 Fay 核心';$('#start').disabled=h.fay_core;
    if(autoConnectWanted&&clientId&&h.model_state==='ready'&&!currentConnected&&!connecting&&!retryTimer)display();
    if(autoConnectWanted&&clientId&&h.fay_connected&&!h.fay_core&&!coreStarting){coreStarting=true;api('start').catch(()=>message('Fay 正在准备，将稍后重试。')).finally(()=>{coreStarting=false;});}
    return h;
  }catch{message('无法连接本机数字人服务。',true);}
}
$('#stage').onclick=enableAudio;
$('#start').onclick=async()=>{try{await api('start');await health();message('Fay 核心已启动。');}catch(e){message(e.message,true);}};
$('#send').onclick=async()=>{
  const text=$('#text').value.trim();if(!text)return;
  if(!await ensureDisplay())return;
  await enableAudio();$('#answer').textContent='';
  try{const r=await api('chat',{text});epoch=Math.max(epoch,r.epoch);}
  catch(e){message(e.message,true);}
};
$('#interrupt').onclick=async()=>{try{const r=await api('interrupt');epoch=Math.max(epoch,r.epoch);message('已打断语音和动作，回到待机。');}catch(e){message(e.message,true);}};
$('#fullscreen').onclick=()=>$('#stage').requestFullscreen().catch(()=>{});
$('#exit-fullscreen').onclick=()=>document.exitFullscreen().catch(()=>{});
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#interrupt').click();});
connect();health();setInterval(health,4000);
