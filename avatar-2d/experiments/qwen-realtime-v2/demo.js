const $=selector=>document.querySelector(selector);
const demo=window.qwenDemo={
  pc:null,ws:null,session:null,ready:false,provider:false,listening:false,wakeState:'off',
  events:[],mic:null,rows:new Map(),voiceRows:[],voiceCounter:0,
  subtitleMode:localStorage.getItem('xiaolin_subtitle_mode')||'auto',
  subtitleFadeTimer:null,userSubFadeTimer:null,soundUnlocked:false,speaking:false
};
demo.takeoverPending=new URLSearchParams(location.search).get('takeover')==='1';
const stage=document.querySelector('.stage');
let stageScroll=0;

function updateFullscreen(){
  const active=document.fullscreenElement===stage||stage.classList.contains('stage-expanded');
  $('#fullscreen').textContent=active?'✕ 退出':'⛶';
  $('#fullscreen').setAttribute('aria-pressed',String(active));
}
function exitStageFallback(){
  if(!stage.classList.contains('stage-expanded'))return;
  stage.classList.remove('stage-expanded');document.body.classList.remove('stage-fullscreen');window.scrollTo(0,stageScroll);updateFullscreen();
}
async function ensureNotNativeFullscreen(){
  if(document.fullscreenElement===stage){try{await document.exitFullscreen();}catch{}}
  updateFullscreen();
}
$('#fullscreen').onclick=async()=>{
  try{
    if(document.fullscreenElement===stage)await document.exitFullscreen();
    else if(stage.classList.contains('stage-expanded'))exitStageFallback();
    else{
      try{if(!stage.requestFullscreen||!document.fullscreenEnabled)throw Error('Fullscreen unavailable');await stage.requestFullscreen();}
      catch{stageScroll=window.scrollY;stage.classList.add('stage-expanded');document.body.classList.add('stage-fullscreen');}
    }
    updateFullscreen();
  }catch(reason){error('全屏切换失败：'+reason.message);}
};
document.addEventListener('fullscreenchange',updateFullscreen);
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){
    if(!$('#fay-modal').classList.contains('hidden'))closeFayModal();
    else if(!$('#workbench-drawer').classList.contains('hidden'))closeWorkbench();
    else exitStageFallback();
  }
});

/* Subtitles */
function formatSubtitleWindow(text){
  const clean=String(text||'').replace(/\s+/g,' ').trim();
  if(!clean)return '';
  const clauses=clean.match(/[^。！？；!?;，,\n]+[。！？；!?;，,\n]*/g)||[clean];
  const maxChars=window.innerWidth<520?18:24;
  const lines=[];
  for(const clause of clauses){
    const t=clause.trim();
    if(!t)continue;
    for(let i=0;i<t.length;i+=maxChars)lines.push(t.slice(i,i+maxChars));
  }
  return lines.slice(-2).join('\n');
}
function updateSubtitleBtn(){
  const labels={auto:'💬 字幕·智能',always:'💬 字幕·常驻',off:'💬 字幕·关'};
  $('#subtitle-btn').textContent=labels[demo.subtitleMode]||'💬 字幕';
  $('#subtitle-btn').classList.toggle('active',demo.subtitleMode!=='off');
  if(demo.subtitleMode==='off'){
    $('#subtitle-layer').classList.add('hidden');
  }else{
    $('#subtitle-layer').classList.remove('hidden');
    if(demo.subtitleMode==='always'&&($('#subtitle-assistant').textContent||$('#subtitle-user').textContent)){
      clearTimeout(demo.subtitleFadeTimer);
      $('#subtitle-layer').classList.remove('faded');
    }
  }
}
$('#subtitle-btn').onclick=()=>{
  const order=['auto','always','off'];
  demo.subtitleMode=order[(order.indexOf(demo.subtitleMode)+1)%order.length];
  localStorage.setItem('xiaolin_subtitle_mode',demo.subtitleMode);
  updateSubtitleBtn();
};
function showUserSubtitle(text){
  if(demo.subtitleMode==='off')return;
  const el=$('#subtitle-user');
  const val=String(text||'').trim();
  if(!val){el.classList.add('hidden');el.textContent='';return;}
  el.textContent='你 · '+val;
  el.classList.remove('hidden');
  clearTimeout(demo.subtitleFadeTimer);
  $('#subtitle-layer').classList.remove('faded');
}
function showAssistantSubtitle(fullText,isSpeaking=true){
  if(demo.subtitleMode==='off')return;
  const el=$('#subtitle-assistant');
  const win=formatSubtitleWindow(fullText);
  if(!win){el.classList.add('hidden');el.textContent='';return;}
  el.textContent=win;
  el.classList.remove('hidden');
  el.classList.toggle('speaking',Boolean(isSpeaking));
  clearTimeout(demo.subtitleFadeTimer);
  $('#subtitle-layer').classList.remove('faded');
}
function scheduleSubtitleFade(){
  $('#subtitle-assistant').classList.remove('speaking');
  if(demo.subtitleMode!=='auto')return;
  clearTimeout(demo.subtitleFadeTimer);
  demo.subtitleFadeTimer=setTimeout(()=>{
    $('#subtitle-layer').classList.add('faded');
  },4200);
}
updateSubtitleBtn();

let reconnectTimer=null,connectDeadline=null,disconnectTimer=null,reconnectAttempts=0,leaving=false;
function reconnectMedia(reason){
  if(leaving||reconnectTimer)return;
  clearTimeout(connectDeadline);clearTimeout(disconnectTimer);
  demo.ready=false;demo.provider=false;demo.listening=false;demo.wakeState='off';demo.speaking=false;updateControls();
  const old=demo.ws;demo.ws=null;if(old){old.onclose=null;old.onerror=null;old.close();}
  if(demo.pc){demo.pc.onconnectionstatechange=null;demo.pc.close();demo.pc=null;}
  stopMic();
  $('#rtc-dot').classList.remove('connected');
  if(reconnectAttempts>=3){$('#rtc').textContent='音视频连接失败';error(reason+'，请点击画面中的“重新连接”。');$('#reconnect').hidden=false;return;}
  reconnectAttempts++;$('#rtc').textContent='重连中（'+reconnectAttempts+'/3）';error('');
  reconnectTimer=setTimeout(()=>{reconnectTimer=null;controlConnect();},1500*reconnectAttempts);
}
function state(value){$('#state').textContent=value;}
function error(value){$('#error').textContent=value;}
function send(value){if(demo.ws?.readyState!==WebSocket.OPEN)throw Error('控制连接尚未就绪');demo.ws.send(JSON.stringify(value));}
function row(role,text,id){
  let element=id&&demo.rows.get(id);
  if(!element){element=document.createElement('div');element.className='message '+role;const label=document.createElement('label');label.textContent=role==='user'?'你':($('#persona-name').textContent||'小霖');element.append(label,document.createElement('span'));$('#messages').append(element);if(id)demo.rows.set(id,element);}
  element.querySelector('span').textContent=text;$('#messages').scrollTop=$('#messages').scrollHeight;
  if(role==='user')showUserSubtitle(text);
  else if(text)showAssistantSubtitle(text,demo.speaking);
  return element;
}
async function sound(){
  const video=$('#avatar');
  video.muted=false;
  await video.play();
  demo.soundUnlocked=true;
  $('#sound').textContent='🔊 已开';
  $('#sound').classList.add('active');
  $('#sound-prompt').classList.add('hidden');
}
function updateControls(){
  const connected=demo.pc?.connectionState==='connected';
  $('#send').disabled=!connected;
  $('#mic').disabled=!connected;
  $('#interrupt').disabled=!demo.provider&&!demo.speaking;
  $('#stop').disabled=!demo.provider&&!demo.mic;
  $('#sleep').disabled=!demo.mic||demo.wakeState!=='awake';
  const micBtn=$('#mic');
  micBtn.classList.toggle('listening',Boolean(demo.mic&&demo.listening&&demo.wakeState!=='awake'));
  micBtn.classList.toggle('awake',Boolean(demo.mic&&demo.wakeState==='awake'));
  if(!demo.mic)micBtn.textContent='🎙️ 开启唤醒';
  else if(demo.wakeState==='awake')micBtn.textContent='🎙️ 对话中';
  else micBtn.textContent='🎙️ 待唤醒';
}
async function connectRtc(){
  const responseConfig=await fetch('/api/rtc-config');if(!responseConfig.ok)throw Error('媒体配置读取失败：'+responseConfig.status);
  const config=await responseConfig.json();const pc=demo.pc=new RTCPeerConnection({...config,iceTransportPolicy:reconnectAttempts?'relay':'all'});
  const media=new MediaStream();$('#avatar').srcObject=media;
  pc.ontrack=event=>media.addTrack(event.track);
  pc.onconnectionstatechange=()=>{
    if(demo.pc!==pc)return;
    const isConn=pc.connectionState==='connected';
    $('#rtc').textContent=isConn?'1080×1920 · 50fps 已连接':'音视频：'+pc.connectionState;
    $('#rtc-dot').classList.toggle('connected',isConn);
    demo.ready=isConn;updateControls();
    if(isConn){
      clearTimeout(connectDeadline);clearTimeout(disconnectTimer);
      $('#reconnect').hidden=true;error('');
      if(!demo.soundUnlocked&&$('#avatar').muted)$('#sound-prompt').classList.remove('hidden');
      if($('#state').textContent==='连接中')state('已连接');
    }
    else if(pc.connectionState==='failed')reconnectMedia('媒体连接失败');
    else if(pc.connectionState==='disconnected'){clearTimeout(disconnectTimer);disconnectTimer=setTimeout(()=>{if(demo.pc===pc&&pc.connectionState==='disconnected')reconnectMedia('媒体连接已断开');},6000);}
  };
  pc.addTransceiver('audio',{direction:'recvonly'});pc.addTransceiver('video',{direction:'recvonly'});
  await pc.setLocalDescription(await pc.createOffer());
  if(pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{
    const complete=()=>{clearTimeout(timer);pc.removeEventListener('icecandidate',candidate);pc.removeEventListener('icegatheringstatechange',gather);resolve();};
    const candidate=event=>{if(event.candidate===null)complete();};
    const gather=()=>{if(pc.iceGatheringState==='complete')complete();};
    const timer=setTimeout(()=>{if(pc.localDescription.sdp.includes('a=candidate:'))complete();else{pc.removeEventListener('icecandidate',candidate);pc.removeEventListener('icegatheringstatechange',gather);reject(Error('音视频候选收集超时'));}},20000);
    pc.addEventListener('icecandidate',candidate);pc.addEventListener('icegatheringstatechange',gather);
  });
  const response=await fetch('/api/offer',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Session':demo.session},body:JSON.stringify(pc.localDescription)});
  if(!response.ok)throw Error('音视频协商失败：'+response.status);
  await pc.setRemoteDescription(await response.json());
  if(demo.pc===pc&&pc.connectionState!=='connected')connectDeadline=setTimeout(()=>{if(demo.pc===pc&&pc.connectionState!=='connected')reconnectMedia('媒体连接超时');},25000);
}
function waitListener(){return new Promise((resolve,reject)=>{const start=Date.now();const timer=setInterval(()=>{if(demo.listening){clearInterval(timer);resolve();}else if(Date.now()-start>7000){clearInterval(timer);reject(Error('唤醒监听启动超时'));}},50);});}
async function stopMic(){
  const mic=demo.mic;demo.mic=null;
  if(mic){mic.worklet.port.onmessage=null;mic.stream.getTracks().forEach(track=>track.stop());mic.worklet.disconnect();mic.source.disconnect();await mic.context.close();}
  updateControls();
}
async function startMic(){
  if(demo.mic){send({type:'stop'});await stopMic();return;}
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  let context;
  try{
    await sound();context=new AudioContext();await context.resume();
    const source=context.createMediaStreamSource(stream);
    const code=`class Mic extends AudioWorkletProcessor{constructor(){super();this.buffer=new Int16Array(1600);this.index=0;this.ratio=sampleRate/16000;this.left=this.ratio;this.sum=0;}sample(value){this.buffer[this.index++]=Math.max(-1,Math.min(1,value))*32767;if(this.index===1600){this.port.postMessage(this.buffer.buffer,[this.buffer.buffer]);this.buffer=new Int16Array(1600);this.index=0;}}process(inputs){const channel=inputs[0]?.[0];if(channel)for(let i=0;i<channel.length;i++){let weight=1;while(weight>1e-9){const take=Math.min(weight,this.left);this.sum+=channel[i]*take;this.left-=take;weight-=take;if(this.left<1e-9){this.sample(this.sum/this.ratio);this.sum=0;this.left=this.ratio;}}}return true;}}registerProcessor('qwen-mic',Mic);`;
    const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));try{await context.audioWorklet.addModule(url);}finally{URL.revokeObjectURL(url);}
    const worklet=new AudioWorkletNode(context,'qwen-mic');const silent=context.createGain();silent.gain.value=0;source.connect(worklet);worklet.connect(silent);silent.connect(context.destination);
    demo.listening=false;send({type:'listen'});await waitListener();
    demo.mic={stream,context,source,worklet};worklet.port.onmessage=event=>{if(demo.mic&&demo.listening&&demo.ws.readyState===WebSocket.OPEN)demo.ws.send(event.data);};
    state('待唤醒·小霖小霖');error('');updateControls();
  }catch(reason){stream.getTracks().forEach(track=>track.stop());if(context)await context.close();throw reason;}
}
function applyFaySummary(fay){
  if(!fay)return;
  demo.fay=fay;
  if(fay.persona_name)$('#persona-name').textContent=fay.persona_name;
  $('#mcp-count-badge').textContent=String(fay.mcp_tool_count||0);
}
function controlConnect(){
  const scope=new URLSearchParams(location.search).get('scope');
  const params=new URLSearchParams();if(scope)params.set('scope',scope);if(demo.takeoverPending)params.set('takeover','1');
  const ws=demo.ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws'+(params.size?'?'+params.toString():''));
  ws.onmessage=async message=>{
    if(demo.ws!==ws||leaving)return;
    const event=JSON.parse(message.data);demo.events.push(event);if(demo.events.length>300)demo.events.shift();
    if(event.type==='ready'){
      demo.session=event.session_id;demo.takeoverPending=false;const cleanUrl=new URL(location.href);cleanUrl.searchParams.delete('takeover');history.replaceState(null,'',cleanUrl);
      applySettings(event.settings);applyFaySummary(event.fay);
      state('准备连接');
      try{await connectRtc();}catch(reason){if(demo.ws===ws)reconnectMedia(reason.message);}
    }else if(event.type==='provider_ready'){
      demo.provider=true;
      state(event.model==='fay-agent'?'Fay认知已就绪':'实时语音已就绪');
      updateControls();
    }else if(event.type==='provider_stopped'){
      demo.provider=false;demo.speaking=false;
      if(!event.listening){demo.listening=false;state('已待机');await stopMic();}
      updateControls();
    }else if(event.type==='listen_ready'){demo.listening=true;updateControls();}
    else if(event.type==='wake_detected'){state('正在唤醒');error('');}
    else if(event.type==='wake_state'){
      demo.wakeState=event.state;demo.listening=event.listening;
      const labels={waiting:'待唤醒·小霖小霖',checking:'识别唤醒词…',awake:'已唤醒·对话中',off:'监听已停'};
      const longLabels={waiting:'等待唤醒：小霖小霖',checking:'正在检查唤醒词',awake:'已唤醒，可以直接说话',off:'唤醒监听已停止'};
      $('#wake-state').textContent=longLabels[event.state]||event.state;
      state(labels[event.state]||event.state);
      updateControls();
    }else if(event.type==='speech_started'){
      const id=event.item_id?'voice-item-'+event.item_id:'voice-'+(++demo.voiceCounter);
      demo.voiceRows.push(id);row('user','正在识别…',id);state('正在聆听');
    }else if(event.type==='speech_stopped'){state('思考中');}
    else if(event.type==='user_text'){
      const id=event.item_id?'voice-item-'+event.item_id:demo.voiceRows.shift();
      demo.voiceRows=demo.voiceRows.filter(x=>x!==id);
      row('user',event.text,id);
    }else if(event.type==='response_started'){
      demo.speaking=true;row('assistant','',event.response_id);state('正在回答');updateControls();
    }else if(event.type==='assistant_delta'){
      const element=demo.rows.get(event.response_id);
      row('assistant',(element?.querySelector('span').textContent||'')+event.text,event.response_id);
    }else if(event.type==='assistant_text'){
      row('assistant',event.text,event.response_id);
    }else if(event.type==='playing'){
      demo.speaking=true;state('播报中');updateControls();
      $('#metrics').textContent='首块音频进入口型后播放延迟约 '+Math.round(event.pcm_to_play_ms)+' ms';
    }else if(event.type==='playback_done'){
      demo.speaking=false;updateControls();
      state(demo.mic?(demo.wakeState==='awake'?'已唤醒·对话中':'待唤醒·小霖小霖'):'可继续提问');
      scheduleSubtitleFade();
    }else if(event.type==='response_done'){demo.lastResponse=event;}
    else if(event.type==='interrupted'){
      demo.speaking=false;updateControls();
      state(demo.mic?'正在聆听':'已打断');
      scheduleSubtitleFade();
    }else if(event.type==='settings_changed'){
      reconnectAttempts=0;applySettings(event.settings);applyFaySummary(event.fay);
      $('#settings-message').textContent='已保存，下一轮使用新配置';
    }else if(event.type==='fay_synced'){
      applyFaySummary(event.fay);
    }else if(event.type==='coordinating'){state('能力调用中');}
    else if(event.type==='capability_result'){demo.lastCapability=event.result;}
    else if(event.type==='gesture'||event.type==='gesture_state'){
      const labels={'welcome-wave':'迎宾挥手','goodbye-wave':'告别挥手','acknowledge-nod':'点头确认','explain-open-palms':'伸手讲解',idle:'自然待机'};
      $('#gesture-state').textContent=labels[event.gesture]||'自然待机';
    }else if(event.type==='error'){error(event.message);state('请检查提示');}
  };
  ws.onclose=event=>{if(demo.ws===ws){if(event.code===4001){reconnectAttempts=3;demo.takeoverPending=true;}reconnectMedia(event.code===4001?'展示已切换至其他设备':'控制连接已断开');}};
  ws.onerror=()=>{if(demo.ws===ws)error('控制连接失败，正在尝试恢复');};
}

$('#question').onsubmit=async event=>{
  event.preventDefault();
  const text=$('#text').value.trim();if(!text)return;
  try{await sound();error('');row('user',text);send({type:'text',text});$('#text').value='';state('正在回答');}
  catch(reason){error(reason.message);}
};
$('#sound').onclick=()=>sound().catch(reason=>error(reason.message));
$('#sound-prompt').onclick=()=>sound().catch(reason=>error(reason.message));
$('#avatar').onclick=()=>{if(!demo.soundUnlocked&&$('#avatar').muted)sound().catch(()=>{});};
$('#mic').onclick=()=>startMic().catch(reason=>error(reason.message));
$('#interrupt').onclick=()=>send({type:'interrupt'});
$('#stop').onclick=async()=>{await stopMic();send({type:'stop'});};
$('#sleep').onclick=()=>send({type:'sleep'});
$('#reconnect').onclick=()=>{demo.takeoverPending=true;reconnectAttempts=0;$('#reconnect').hidden=true;reconnectMedia('重新连接');};
addEventListener('pagehide',()=>{leaving=true;clearTimeout(reconnectTimer);clearTimeout(connectDeadline);clearTimeout(disconnectTimer);demo.mic?.stream.getTracks().forEach(track=>track.stop());demo.ws?.close();demo.pc?.close();});

const flagNames=['coordinator_enabled','mcp_enabled','knowledge_enabled','memory_enabled','gestures_enabled'];
function applySettings(config){
  if(!config)return;
  demo.settings=config;
  const mode=config.dialogue_mode||'qwen_realtime';
  $('#current-model').textContent=config.model;
  $('#current-engine').textContent=mode==='fay_agent'?'模式 B · Fay 完整认知引擎':'模式 A · 极速实时语音 + Fay同步';
  $('#model-choice').value=config.model;
  $('#lipsync-choice').value=config.lipsync_backend||'wav2lip';
  $('#dialogue-mode-choice').value=mode;
  $('#mode-qwen').classList.toggle('active',mode==='qwen_realtime');
  $('#mode-fay').classList.toggle('active',mode==='fay_agent');
  for(const name of flagNames)$('#'+name).checked=config[name];
  const labels={mcp_enabled:'Fay MCP',knowledge_enabled:'知识库',memory_enabled:'记忆',gestures_enabled:'手势'};
  const enabled=Object.keys(labels).filter(key=>config.coordinator_enabled&&config[key]).map(key=>labels[key]);
  $('#capability-status').textContent=(mode==='fay_agent'?'当前处于 Fay 认知引擎模式 · ':'')+(enabled.length?'模型协同：'+enabled.join(' / '):'纯语音模式 · 能力协同已关闭');
}

async function api(path,options={}){
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Demo-Session':demo.session,...options.headers}});
  if(!response.ok)throw Error(await response.text());
  return response.json();
}

async function switchDialogueMode(targetMode){
  if(!demo.settings||demo.settings.dialogue_mode===targetMode)return;
  try{
    const {revision,...payload}=demo.settings;
    payload.dialogue_mode=targetMode;
    state(targetMode==='fay_agent'?'切换 Fay…':'切换极速…');
    const updated=await api('/api/settings',{method:'POST',body:JSON.stringify(payload)});
    applySettings(updated);
    state(targetMode==='fay_agent'?'Fay 认知模式':'极速语音模式');
  }catch(reason){error('模式切换失败：'+reason.message);}
}
$('#mode-qwen').onclick=()=>switchDialogueMode('qwen_realtime');
$('#mode-fay').onclick=()=>switchDialogueMode('fay_agent');

async function refreshCapabilities(){
  const data=await api('/api/capabilities');demo.capabilities=data;
  if(data.fay)applyFaySummary(data.fay);
  $('#retrieval-models').textContent='Embedding：'+data.embedding_model+'；Rerank：'+data.rerank_model;
  $('#memory-count').textContent='关联记忆 '+(data.counts.memory||0)+' 条；知识片段 '+(data.counts.knowledge||0)+' 条。命名空间：'+data.namespace;
  $('#knowledge-documents').replaceChildren();
  for(const doc of data.knowledge_documents){const item=document.createElement('div');item.className='doc';const title=document.createElement('span');title.textContent=doc.title;const remove=document.createElement('button');remove.textContent='删除';remove.onclick=async()=>{try{await api('/api/knowledge/'+doc.id,{method:'DELETE'});await refreshCapabilities();}catch(reason){$('#knowledge-message').textContent=reason.message;}};item.append(title,remove);$('#knowledge-documents').append(item);}
  const names={attendance_result:'打卡结果',mcp_result:'MCP调用',coordinated:'能力规划',knowledge_retrieved:'知识检索',memory_retrieved:'记忆检索',memory_saved:'记忆已保存',gesture_started:'动作开始'};
  $('#audit').textContent=data.audit.map(row=>new Date(row.created*1000).toLocaleTimeString()+' '+(names[row.event]||row.event)+' '+row.data).join('\n');
}

/* Workbench Drawer */
function openWorkbench(view='chat'){
  ensureNotNativeFullscreen().then(()=>{
    $('#workbench-drawer').classList.remove('hidden');
    for(const button of document.querySelectorAll('[data-view]')){
      if(button.dataset.view===view)button.click();
    }
  });
}
function closeWorkbench(){$('#workbench-drawer').classList.add('hidden');}
$('#workbench-btn').onclick=()=>openWorkbench('chat');
$('#status-pill').onclick=()=>openWorkbench('chat');
$('#close-workbench').onclick=closeWorkbench;
$('#workbench-drawer').onclick=e=>{if(e.target===$('#workbench-drawer'))closeWorkbench();};

for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>{
  for(const name of ['chat','settings','knowledge'])$('#'+name+'-view').classList.toggle('hidden',name!==button.dataset.view);
  for(const other of document.querySelectorAll('[data-view]'))other.classList.toggle('selected',other===button);
  if(button.dataset.view==='knowledge')refreshCapabilities().catch(reason=>$('#knowledge-message').textContent=reason.message);
};

/* Fay Native Console Modal */
function setFayTab(url){
  $('#fay-frame').src=url;
  $('#fay-open-tab').href=url;
  for(const btn of document.querySelectorAll('[data-fay-src]')){
    btn.classList.toggle('active',btn.dataset.faySrc===url);
  }
}
function openFayModal(url){
  ensureNotNativeFullscreen().then(()=>{
    setFayTab(url);
    $('#fay-modal').classList.remove('hidden');
  });
}
async function syncFayFromBackend(){
  try{
    const summary=await api('/api/fay/sync',{method:'POST'});
    applyFaySummary(summary);
    return summary;
  }catch{return null;}
}
async function closeFayModal(){
  $('#fay-modal').classList.add('hidden');
  $('#fay-frame').src='about:blank';
  await syncFayFromBackend();
}
$('#fay-persona-btn').onclick=()=>openFayModal('/fay/setting');
$('#fay-mcp-btn').onclick=()=>openFayModal('/Page3');
$('#open-fay-from-settings').onclick=()=>openFayModal('/fay/setting');
$('#open-mcp-from-settings').onclick=()=>openFayModal('/Page3');
$('#fay-sync-close').onclick=()=>closeFayModal();
$('#fay-modal').onclick=e=>{if(e.target===$('#fay-modal'))closeFayModal();};
for(const btn of document.querySelectorAll('[data-fay-src]'))btn.onclick=()=>setFayTab(btn.dataset.faySrc);

window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.data&&event.data.type==='xiaolin_fay_updated'){
    syncFayFromBackend();
  }
});

$('#reload-settings').onclick=()=>api('/api/settings').then(applySettings).catch(reason=>$('#settings-message').textContent=reason.message);
$('#sync-fay-now').onclick=async()=>{
  const s=await syncFayFromBackend();
  $('#settings-message').textContent=s?('已同步 Fay 人设（'+s.persona_name+'）与 '+s.mcp_tool_count+' 个在线 MCP 工具'):'同步失败，请检查 Fay 后台';
};
$('#save-settings').onclick=async()=>{
  $('#save-settings').disabled=true;
  $('#settings-message').textContent='正在保存并应用配置，请稍候…';
  try{
    const value={dialogue_mode:$('#dialogue-mode-choice').value,model:$('#model-choice').value,lipsync_backend:$('#lipsync-choice').value};
    for(const name of flagNames)value[name]=$('#'+name).checked;
    const result=await api('/api/settings',{method:'POST',body:JSON.stringify(value)});
    applySettings(result);
    $('#settings-message').textContent='已保存，下一轮使用新配置';
  }catch(reason){$('#settings-message').textContent=reason.message;}
  finally{$('#save-settings').disabled=false;}
};
$('#refresh-capabilities').onclick=()=>refreshCapabilities().catch(reason=>$('#knowledge-message').textContent=reason.message);
$('#add-knowledge').onclick=async()=>{
  const button=$('#add-knowledge');button.disabled=true;$('#knowledge-message').textContent='正在生成向量并入库…';
  try{
    const result=await api('/api/knowledge',{method:'POST',body:JSON.stringify({title:$('#knowledge-title').value,content:$('#knowledge-content').value})});
    $('#knowledge-message').textContent='已入库 '+result.ids.length+' 个片段';$('#knowledge-content').value='';
    await refreshCapabilities();
  }catch(reason){$('#knowledge-message').textContent=reason.message;}
  finally{button.disabled=false;}
};
controlConnect();
