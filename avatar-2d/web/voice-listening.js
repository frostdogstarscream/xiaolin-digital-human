// Local VAD ends short microphone utterances; only local FunASR sees audio.
let voiceListener=null;
function stopWakeListening(){if(voiceListener){const previous=voiceListener;voiceListener=null;previous.stop();}}
function pauseWakeForOutput(){voiceListener?.pauseForOutput();}
class WakeListening{
  constructor(stream,context){
    this.stream=stream;this.context=context;this.running=true;this.busy=false;this.recorder=null;
    this.abort=new AbortController();this.analyser=context.createAnalyser();this.analyser.fftSize=1024;
    this.source=context.createMediaStreamSource(stream);this.source.connect(this.analyser);
    this.samples=new Float32Array(this.analyser.fftSize);
    this.arm();this.timer=setInterval(()=>this.tick(),80);
  }
  arm(){
    if(!this.running)return;
    this.busy=false;this.started=performance.now();this.lastSound=0;this.firstSound=0;
    const type=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    const recorder=new MediaRecorder(this.stream,type?{mimeType:type}:undefined),chunks=[];
    this.recorder=recorder;
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=()=>this.finish(chunks,recorder.mimeType);
    recorder.onerror=()=>{stopWakeListening();$('#mic-status').textContent='录音设备出错，请重新开启语音唤醒。';};
    recorder.start(200);$('#record').textContent='停止语音唤醒';$('#record').disabled=false;$('#cancel-record').disabled=false;
  }
  tick(){
    if(!this.running||this.busy||this.recorder?.state!=='recording')return;
    this.analyser.getFloatTimeDomainData(this.samples);
    const rms=Math.sqrt(this.samples.reduce((sum,x)=>sum+x*x,0)/this.samples.length),now=performance.now();
    if(rms>.015){if(!this.firstSound)this.firstSound=now;this.lastSound=now;}
    const ended=this.firstSound&&now-this.lastSound>900;
    const idle=!this.firstSound&&now-this.started>4000;
    if(ended||idle||now-this.started>15000){this.busy=true;this.recorder.stop();}
  }
  async waitForOutput(){
    do{
      await new Promise(resolve=>setTimeout(resolve,400));if(!this.running)return;
      const state=await api('voice-state',{},this.abort.signal);
      if(!state.busy){$('#mic-status').textContent=state.awake?'小霖正在聆听，可以直接提问；60 秒无交互后休眠。':'请说“'+state.word+'”唤醒小霖。';await new Promise(resolve=>setTimeout(resolve,600));return;}
    }while(this.running);
  }
  async pauseForOutput(){
    if(!this.running||this.busy)return;
    this.busy=true;
    // Discard speech captured during a typed reply too, preventing speaker feedback.
    this.recorder.onstop=()=>{};if(this.recorder.state==='recording')this.recorder.stop();
    $('#mic-status').textContent='小霖正在播报，播报完成后继续聆听。';
    try{await this.waitForOutput();this.arm();}
    catch(e){if(e.name!=='AbortError'){stopWakeListening();$('#mic-status').textContent='连接中断，请重新开启语音唤醒。';}}
  }
  async finish(chunks,type){
    if(!this.running)return;
    if(!this.firstSound||this.lastSound-this.firstSound<160){this.arm();return;}
    try{
      $('#mic-status').textContent='本机识别中…';
      const response=await fetch('/api/asr',{method:'POST',headers:{'Content-Type':type,'X-Avatar-Client':'1','X-Avatar-Viewer':clientId||''},
        body:new Blob(chunks,{type}),signal:this.abort.signal});
      if(!response.ok)throw Error(await response.text());
      const result=await response.json();if(!this.running)return;
      if(!result.text){$('#mic-status').textContent='正在本机聆听，请说“小霖小霖”。';this.arm();return;}
      $('#text').value=result.text;$('#transcript').textContent='识别结果：'+result.text;
      if($('#auto-send-voice').checked){
        const decision=await api('voice-input',{text:result.text},this.abort.signal);
        if(!this.running)return;
        $('#mic-status').textContent=decision.status==='waiting'?decision.prompt:decision.status==='waking'?'已唤醒小霖，正在播放欢迎词…':'小霖正在回答，播报完成后继续聆听。';
        if(decision.status!=='waiting'){
          await this.waitForOutput();
        }
      }else $('#mic-status').textContent='识别文字已填入输入框，正在继续聆听。';
      this.arm();
    }catch(e){
      if(e.name!=='AbortError'){$('#mic-status').textContent='语音处理未完成：'+e.message;message('请检查本机服务，或停止语音唤醒后重试。',true);}
      if(this.running)stopWakeListening();
    }
  }
  stop(){
    this.running=false;this.abort.abort();clearInterval(this.timer);
    if(this.recorder?.state==='recording')this.recorder.stop();
    this.source.disconnect();this.stream.getTracks().forEach(track=>track.stop());this.context.close().catch(()=>{});
    $('#record').textContent='开启语音唤醒';$('#record').disabled=false;$('#cancel-record').disabled=true;
  }
}
async function startWakeListening(){
  if(voiceListener){cancelMicrophone();await api('voice-sleep');$('#mic-status').textContent='已关闭麦克风，回到待唤醒。';return;}
  if(!await ensureDisplay())return;
  cancelMicrophone();const serial=microphoneSerial;
  $('#record').disabled=true;$('#cancel-record').disabled=false;
  $('#mic-status').textContent='请允许麦克风权限，开启后说“小霖小霖”。';
  let stream,context;
  try{
    const Context=window.AudioContext||window.webkitAudioContext;
    if(!Context||!navigator.mediaDevices?.getUserMedia)throw Error('请使用支持麦克风的现代浏览器');
    context=new Context();await context.resume();enableAudio();
    await api('interrupt');
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(serial!==microphoneSerial){stream.getTracks().forEach(t=>t.stop());await context.close();return;}
    voiceListener=new WakeListening(stream,context);
    $('#mic-status').textContent='正在本机聆听，请说“小霖小霖”唤醒。';
  }catch(e){stream?.getTracks().forEach(t=>t.stop());context?.close().catch(()=>{});cancelMicrophone();$('#mic-status').textContent=e.name==='NotAllowedError'?'麦克风未获授权，请允许后重试。':'无法开启语音唤醒：'+e.message;}
}
