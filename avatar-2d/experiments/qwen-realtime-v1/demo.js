const $=selector=>document.querySelector(selector);
const demo=window.qwenDemo={pc:null,ws:null,session:null,ready:false,provider:false,events:[],mic:null,rows:new Map(),voiceRows:[],voiceCounter:0};
function state(value){$('#state').textContent=value;}
function error(value){$('#error').textContent=value;}
function send(value){if(demo.ws?.readyState!==WebSocket.OPEN)throw Error('控制连接尚未就绪');demo.ws.send(JSON.stringify(value));}
function row(role,text,id){
  let element=id&&demo.rows.get(id);
  if(!element){element=document.createElement('div');element.className='message '+role;const label=document.createElement('label');label.textContent=role==='user'?'你':'小霖';element.append(label,document.createElement('span'));$('#messages').append(element);if(id)demo.rows.set(id,element);}
  element.querySelector('span').textContent=text;$('#messages').scrollTop=$('#messages').scrollHeight;return element;
}
async function sound(){const video=$('#avatar');video.muted=false;await video.play();$('#sound').textContent='声音已开启';}
function updateControls(){const connected=demo.pc?.connectionState==='connected';$('#send').disabled=!connected;$('#mic').disabled=!connected;$('#interrupt').disabled=!demo.provider;$('#stop').disabled=!demo.provider&&!demo.mic;}
async function connectRtc(){
  const config=await(await fetch('/api/rtc-config')).json();const pc=demo.pc=new RTCPeerConnection({...config,bundlePolicy:'max-bundle'});
  const media=new MediaStream();$('#avatar').srcObject=media;
  pc.ontrack=event=>media.addTrack(event.track);
  pc.onconnectionstatechange=()=>{$('#rtc').textContent=pc.connectionState==='connected'?'1080p · 音视频已连接':'音视频：'+pc.connectionState;demo.ready=pc.connectionState==='connected';updateControls();};
  pc.addTransceiver('audio',{direction:'recvonly'});pc.addTransceiver('video',{direction:'recvonly'});
  await pc.setLocalDescription(await pc.createOffer());
  if(pc.iceGatheringState!=='complete'&&!pc.localDescription.sdp.includes(' typ relay '))await new Promise((resolve,reject)=>{
    const complete=()=>{clearTimeout(timer);pc.removeEventListener('icecandidate',candidate);pc.removeEventListener('icegatheringstatechange',gather);resolve();};
    const candidate=event=>{if(event.candidate?.type==='relay')complete();};
    const gather=()=>{if(pc.iceGatheringState==='complete')complete();};
    const timer=setTimeout(()=>{if(pc.localDescription.sdp.includes('a=candidate:'))complete();else{pc.removeEventListener('icecandidate',candidate);pc.removeEventListener('icegatheringstatechange',gather);reject(Error('音视频候选收集超时'));}},12000);
    pc.addEventListener('icecandidate',candidate);pc.addEventListener('icegatheringstatechange',gather);
  });
  const response=await fetch('/api/offer',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Session':demo.session},body:JSON.stringify(pc.localDescription)});
  if(!response.ok)throw Error('音视频协商失败：'+response.status);
  await pc.setRemoteDescription(await response.json());
}
function waitProvider(){return new Promise((resolve,reject)=>{if(demo.provider)return resolve();const start=Date.now();const timer=setInterval(()=>{if(demo.provider){clearInterval(timer);resolve();}else if(Date.now()-start>22000){clearInterval(timer);reject(Error('实时模型连接超时'));}},50);});}
async function stopMic(){
  const mic=demo.mic;demo.mic=null;
  if(mic){mic.worklet.port.onmessage=null;mic.stream.getTracks().forEach(track=>track.stop());mic.worklet.disconnect();mic.source.disconnect();await mic.context.close();}
  $('#mic').textContent='开启实时对话';updateControls();
}
async function startMic(){
  if(demo.mic)return;
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  let context;
  try{
    await sound();context=new AudioContext({sampleRate:16000});await context.resume();
    if(context.sampleRate!==16000)throw Error('浏览器未提供16kHz采样率');
    const source=context.createMediaStreamSource(stream);
    const code=`class Mic extends AudioWorkletProcessor{constructor(){super();this.buffer=new Int16Array(1600);this.index=0;}process(inputs){const channel=inputs[0]?.[0];if(channel)for(let i=0;i<channel.length;i++){this.buffer[this.index++]=Math.max(-1,Math.min(1,channel[i]))*32767;if(this.index===1600){this.port.postMessage(this.buffer.buffer,[this.buffer.buffer]);this.buffer=new Int16Array(1600);this.index=0;}}return true;}}registerProcessor('qwen-mic',Mic);`;
    const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));try{await context.audioWorklet.addModule(url);}finally{URL.revokeObjectURL(url);}
    const worklet=new AudioWorkletNode(context,'qwen-mic');const silent=context.createGain();silent.gain.value=0;source.connect(worklet);worklet.connect(silent);silent.connect(context.destination);
    send({type:'start'});await waitProvider();
    demo.mic={stream,context,source,worklet};worklet.port.onmessage=event=>{if(demo.mic&&demo.provider&&demo.ws.readyState===WebSocket.OPEN)demo.ws.send(event.data);};
    $('#mic').textContent='麦克风已开启';state('正在聆听');error('');updateControls();
  }catch(reason){stream.getTracks().forEach(track=>track.stop());if(context)await context.close();throw reason;}
}
function controlConnect(){
  const ws=demo.ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
  ws.onmessage=async message=>{
    const event=JSON.parse(message.data);demo.events.push(event);if(demo.events.length>300)demo.events.shift();
    if(event.type==='ready'){
      demo.session=event.session_id;state('模型待连接');try{await connectRtc();}catch(reason){error(reason.message);}
    }else if(event.type==='provider_ready'){demo.provider=true;state('实时模型已连接');updateControls();}
    else if(event.type==='provider_stopped'){demo.provider=false;state('对话已停止');await stopMic();updateControls();}
    else if(event.type==='speech_started'){const id='voice-'+(++demo.voiceCounter);demo.voiceRows.push(id);row('user','正在识别…',id);state('正在聆听');}
    else if(event.type==='speech_stopped'){state('正在回答');}
    else if(event.type==='user_text'){row('user',event.text,demo.voiceRows.shift());}
    else if(event.type==='response_started'){row('assistant','',event.response_id);state('正在回答');}
    else if(event.type==='assistant_delta'){const element=demo.rows.get(event.response_id);row('assistant',(element?.querySelector('span').textContent||'')+event.text,event.response_id);}
    else if(event.type==='assistant_text'){row('assistant',event.text,event.response_id);}
    else if(event.type==='playing'){state('正在播报');$('#metrics').textContent='首块PCM进入口型后，播放回调约 '+Math.round(event.pcm_to_play_ms)+' ms';}
    else if(event.type==='playback_done'){state(demo.mic?'正在聆听':'可以继续提问');}
    else if(event.type==='response_done'){demo.lastResponse=event;}
    else if(event.type==='interrupted'){state(demo.mic?'正在聆听':'已打断');}
    else if(event.type==='error'){error(event.message);state('请检查提示');}
  };
  ws.onclose=()=>{demo.provider=false;demo.ready=false;stopMic();demo.pc?.close();state('连接已关闭，请刷新重连');updateControls();};
  ws.onerror=()=>error('控制连接失败，请检查登录与网络');
}
$('#question').onsubmit=async event=>{event.preventDefault();const text=$('#text').value.trim();if(!text)return;try{await stopMic();await sound();error('');row('user',text);send({type:'text',text});$('#text').value='';state('正在回答');}catch(reason){error(reason.message);}};
$('#sound').onclick=()=>sound().catch(reason=>error(reason.message));
$('#mic').onclick=()=>startMic().catch(reason=>error(reason.message));
$('#interrupt').onclick=()=>send({type:'interrupt'});
$('#stop').onclick=async()=>{await stopMic();send({type:'stop'});};
addEventListener('pagehide',()=>{demo.mic?.stream.getTracks().forEach(track=>track.stop());demo.ws?.close();demo.pc?.close();});
controlConnect();
