// Exercise actual VAD/wake browser code with deterministic audio and transport.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
async function main(){
  let now=0,amplitude=0,recorders=[],requests=[],stopped=0,outputBusy=false,asrText='小霖小霖';
  const nodes=new Map(),node=s=>{if(!nodes.has(s))nodes.set(s,{textContent:'',value:'',checked:true,disabled:false});return nodes.get(s);};
  class Recorder{
    static isTypeSupported(){return true;}
    constructor(){this.mimeType='audio/webm';this.state='inactive';recorders.push(this);}
    start(){this.state='recording';}
    stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['sample'])});this.onstop?.();}
  }
  const stream={getTracks:()=>[{stop(){stopped++;}}]},context={
    createAnalyser:()=>({fftSize:1024,getFloatTimeDomainData:a=>a.fill(amplitude)}),
    createMediaStreamSource:()=>({connect(){},disconnect(){}}),close:async()=>{}};
  const c=vm.createContext({console,Blob,AbortController,MediaRecorder:Recorder,Float32Array,performance:{now:()=>now},
    $:node,clientId:'test',setInterval:()=>1,clearInterval(){},setTimeout:fn=>{fn();return 1;},
    message(){},fetch:async(url,opts)=>{requests.push(url);assert.equal(opts.headers['X-Avatar-Viewer'],'test');return {ok:true,json:async()=>({text:asrText})};},
    api:async(route)=>{requests.push(route);return route==='voice-state'?{busy:outputBusy,awake:true}:route==='voice-input'?{status:'waking'}:{ok:true};},stream,context});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/voice-listening.js'),'utf8'),c);
  vm.runInContext('voiceListener=new WakeListening(stream,context)',c);
  const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
  const tick=async(t,a)=>{now=t;amplitude=a;vm.runInContext('voiceListener.tick()',c);await settle();};
  await tick(4100,0);assert.equal(requests.length,0,'Silence must not call ASR or cloud');
  await tick(4200,.05);await tick(4500,.05);await tick(5500,0);
  assert.ok(requests.includes('/api/asr'));assert.ok(requests.includes('voice-input'));
  assert.ok(requests.includes('voice-state'),'Wait for welcome playback before rearming');
  assert.equal(recorders.at(-1).state,'recording');
  const before=requests.filter(x=>x==='/api/asr').length;
  // A typed reply must discard any partial microphone clip, wait, then rearm.
  outputBusy=true;vm.runInContext('pauseWakeForOutput()',c);assert.equal(recorders.at(-1).state,'inactive');
  outputBusy=false;await settle();assert.equal(recorders.at(-1).state,'recording');
  assert.equal(requests.filter(x=>x==='/api/asr').length,before);
  vm.runInContext('stopWakeListening()',c);await settle();assert.equal(stopped,1);
  assert.equal(recorders.at(-1).state,'inactive');assert.equal(node('#cancel-record').disabled,true);
  console.log('PASS: silence discarded, speech-end ASR, wake gate, playback pause/resume, external speech discard, microphone release');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
