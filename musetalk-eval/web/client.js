const $=s=>document.querySelector(s),client=crypto.randomUUID();let pc=null,state=null,connecting=false,lastPlayedId=null;
async function api(route,body={}){const r=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Eval-Request':'1','X-Eval-Client':client},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());return r.json();}
function status(text){$('#status').textContent=text;}
function close(){lastPlayedId=null;if(pc){pc.onconnectionstatechange=null;pc.close();pc=null;}$('#player').srcObject=null;$('#player').hidden=true;$('#rest').hidden=false;}
async function connect(){
 if(connecting)return;if(pc?.connectionState==='connected')return;connecting=true;close();status('正在连接当前后端的音视频…');
 try{
  pc=new RTCPeerConnection({iceServers:[]});const stream=new MediaStream();$('#player').srcObject=stream;
  pc.addTransceiver('audio',{direction:'recvonly'});pc.addTransceiver('video',{direction:'recvonly'});
  pc.ontrack=e=>{stream.addTrack(e.track);$('#player').play().then(()=>{$('#player').hidden=false;$('#rest').hidden=true;}).catch(()=>status('请点击人物画面启用播放'));};
  pc.onconnectionstatechange=()=>status(pc?.connectionState==='connected'?'已连接，可以播放固定语音和动作。':'音视频状态：'+(pc?.connectionState||'已关闭'));
  await pc.setLocalDescription(await pc.createOffer());
  if(pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('音视频协商超时')),8000);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});});
  const answer=await api('offer',{sdp:pc.localDescription.sdp,type:'offer'});await pc.setRemoteDescription(answer);
 }catch(e){close();status(e.message);}finally{connecting=false;}
}
async function health(){try{const first=state===null,r=await fetch('/api/health');state=await r.json();if(first&&state.backend)$('#backend').value=state.backend;$('#active-backend').textContent=state.backend==='musetalk'?'MuseTalk 1.5':'Wav2Lip';$('#fps').textContent=state.rtc_connected?state.fps.toFixed(1)+' fps':'—';$('#memory').textContent=Math.round(state.gpu_allocated_mb)+' / '+Math.round(state.gpu_peak_mb)+' MB';$('#queue').textContent=state.queue;
 const job=state.jobs.filter(j=>j.backend===state.backend).at(-1);$('#latency').textContent=job?.first_video_at?((job.first_video_at-job.submitted_at)*1000).toFixed(0)+' ms':'—';
 const playing=state.jobs.find(j=>j.id===lastPlayedId);if(playing?.status==='ready'){lastPlayedId=null;status('本段语音已播完，人物动作按原时间轴继续。');}
 if(state.state==='loading')status('正在准备模型与人物缓存，首次加载需要稍等…');if(state.state==='error')status('加载失败：'+state.error+'，请检查实验日志。');
 if(state.state==='ready'&&!pc&&!connecting)status((state.backend==='musetalk'?'MuseTalk 1.5':'Wav2Lip')+' 已就绪，请连接音视频。');
 $('#connect').disabled=state.state!=='ready';$('#switch').disabled=state.state==='loading';
}catch{status('实验服务尚未启动，请运行 Start-MuseTalk-Eval.cmd');}}
$('#connect').onclick=connect;$('#stage').onclick=$('#audio').onclick=()=>{$('#player').muted=false;$('#player').play().catch(()=>{});};
$('#switch').onclick=async()=>{try{close();const target=$('#backend').value;await api('backend',{backend:target});status('正在切换后端…');for(let i=0;i<240;i++){await new Promise(r=>setTimeout(r,1000));await health();if(state.state==='error')return;if(state.state==='ready'&&state.backend===target){await connect();return;}}status('准备时间较长，请查看实验日志。');}catch(e){status(e.message);}};
document.querySelectorAll('[data-action]').forEach(button=>button.onclick=async()=>{try{if(pc?.connectionState!=='connected'){status('请先连接音视频。');return;}$('#player').muted=false;await $('#player').play();const job=await api('play',{fixture:$('#fixture').value,action:button.dataset.action});lastPlayedId=job.id;status('正在播放：'+button.textContent);}catch(e){status(e.message);}});
$('#stop').onclick=()=>api('interrupt').then(()=>{lastPlayedId=null;status('已停止，旧音频已丢弃。');}).catch(e=>status(e.message));
$('#motion').onclick=()=>api('action',{action:'acknowledge-nod'}).catch(e=>status(e.message));
$('#review').onclick=()=>{const action=$('#review-action').value;$('#reviews').replaceChildren();const pair=[];for(const [suffix,title] of [['full','全身对照'],['mouth','嘴部放大对照']]){const p=document.createElement('p');p.textContent=title;const v=document.createElement('video');v.controls=true;v.preload='metadata';v.muted=suffix==='mouth';v.src='/outputs/comparisons/'+action+'-long-'+suffix+'.mp4';pair.push(v);$('#reviews').append(p,v);}for(const v of pair){v.onplay=()=>{for(const other of pair)if(other!==v&&other.paused){other.currentTime=v.currentTime;other.play().catch(()=>{});}};v.onpause=()=>{for(const other of pair)if(other!==v&&!other.paused)other.pause();};v.onseeked=()=>{for(const other of pair)if(other!==v&&Math.abs(other.currentTime-v.currentTime)>.12)other.currentTime=v.currentTime;};}pair[0].ontimeupdate=()=>{if(Math.abs(pair[0].currentTime-pair[1].currentTime)>.2)pair[1].currentTime=pair[0].currentTime;};};
async function report(){try{const r=await(await fetch('/outputs/evaluation-report.json')).json();if(r.realtime?.status==='REAL_WEBRTC_EVALUATION_COMPLETE'){const candidate=r.realtime.results.find(x=>x.backend==='musetalk');$('#report-summary').textContent=(r.realtime.performance_pass?'候选性能已通过':'候选性能未通过')+'：MuseTalk 实收 '+candidate.received_fps.toFixed(1)+' fps，首帧 P95 '+Math.round(candidate.p95_first_video_seconds*1000)+' ms。正式默认保留 Wav2Lip，画质待人工确认。';}}catch{}}
window.addEventListener('beforeunload',close);health();report();setInterval(health,2000);
