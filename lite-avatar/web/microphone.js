// Audio stays on localhost: MediaRecorder -> local FunASR. The recognized question
// passes the wake gate before Fay chat. Microphone requires an explicit click.
let microphoneStream=null,microphoneRecorder=null,microphoneTimer=null;
let microphoneSerial=0,microphoneAbort=null,microphoneActive=false;

function releaseMicrophone(){
  clearTimeout(microphoneTimer);microphoneTimer=null;
  if(microphoneStream)microphoneStream.getTracks().forEach(track=>track.stop());
  microphoneStream=null;microphoneActive=false;
  $('#record').textContent=$('#continuous-wake')?.checked?'开启语音唤醒':'开始录音';$('#record').disabled=false;
  $('#cancel-record').disabled=true;
}
function cancelMicrophone(){
  if(typeof stopWakeListening==='function')stopWakeListening();
  microphoneSerial++;microphoneAbort?.abort();microphoneAbort=null;
  if(microphoneRecorder?.state==='recording')microphoneRecorder.stop();
  microphoneRecorder=null;releaseMicrophone();
}
async function finishMicrophone(chunks,type,serial){
  releaseMicrophone();if(serial!==microphoneSerial)return;
  $('#record').disabled=true;$('#cancel-record').disabled=false;
  $('#mic-status').textContent='本机正在识别…';
  microphoneAbort=new AbortController();
  try{
    const response=await fetch('/api/asr',{method:'POST',headers:{'Content-Type':type,'X-Avatar-Client':'1','X-Avatar-Viewer':clientId||''},
      body:new Blob(chunks,{type}),signal:microphoneAbort.signal});
    if(!response.ok)throw Error(await response.text());
    const result=await response.json();if(serial!==microphoneSerial)return;
    if(!result.text){$('#mic-status').textContent='没有识别到清晰语音，请重试。';return;}
    const text=result.text.trim();
    $('#text').value=text;$('#transcript').textContent='识别结果：'+text;
    $('#mic-status').textContent='本机识别完成，用时 '+Number(result.inference_seconds).toFixed(2)+' 秒。';
    if(text.length>300){message('识别文字较长，请编辑为 300 字以内后发送。',true);return;}
    if($('#auto-send-voice').checked){
      const decision=await api('voice-input',{text});
      $('#mic-status').textContent=decision.status==='waiting'?decision.prompt:decision.status==='waking'?'已唤醒小霖，正在播放欢迎词。':'问题已发送，小霖正在回答。';
    }
  }catch(e){if(e.name!=='AbortError'){$('#mic-status').textContent=e.message;message('语音识别未完成。',true);}}
  finally{if(serial===microphoneSerial){microphoneAbort=null;$('#record').disabled=false;$('#cancel-record').disabled=true;}}
}
$('#record').onclick=async()=>{
  if($('#continuous-wake')?.checked){await startWakeListening();return;}
  if(microphoneActive){microphoneRecorder.stop();return;}
  if(!await ensureDisplay())return;
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){message('当前浏览器不支持录音，请使用支持麦克风的 Edge 或 Chrome。',true);return;}
  cancelMicrophone();const serial=microphoneSerial;
  $('#record').disabled=true;
  try{
    await enableAudio();
    await api('interrupt');
    $('#cancel-record').disabled=false;
    $('#mic-status').textContent='正在请求麦克风权限，请在浏览器提示中允许；也可点击取消。';
    // Permission is requested only in response to this explicit button click.
    const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(serial!==microphoneSerial){stream.getTracks().forEach(t=>t.stop());return;}
    microphoneStream=stream;
    const type=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    const recorder=new MediaRecorder(stream,type?{mimeType:type}:undefined);
    microphoneRecorder=recorder;const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=()=>finishMicrophone(chunks,recorder.mimeType,serial);
    recorder.onerror=()=>{cancelMicrophone();$('#mic-status').textContent='录音设备发生错误，请重试。';};
    microphoneActive=true;$('#record').disabled=false;$('#cancel-record').disabled=false;
    $('#record').textContent='结束录音并识别';$('#mic-status').textContent='正在录音，最长 30 秒；说完请点击结束。';
    recorder.start(250);
    microphoneTimer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},29500);
  }catch(e){cancelMicrophone();$('#mic-status').textContent=e.name==='NotAllowedError'?'麦克风未获授权，请在浏览器中允许后重试。':e.name==='NotFoundError'?'未找到可用麦克风，请连接录音设备。':'无法启动麦克风：'+e.message;}
};
$('#cancel-record').onclick=()=>{cancelMicrophone();api('voice-sleep').catch(()=>{});$('#mic-status').textContent='麦克风已关闭，回到待唤醒。';};
$('#interrupt').addEventListener('click',()=>{cancelMicrophone();$('#mic-status').textContent='录音与识别已停止。';});
window.addEventListener('beforeunload',cancelMicrophone);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&(microphoneActive||microphoneAbort||voiceListener)){cancelMicrophone();api('voice-sleep').catch(()=>{});}});
if($('#continuous-wake'))$('#continuous-wake').onchange=()=>{cancelMicrophone();api('voice-sleep').catch(()=>{});};
