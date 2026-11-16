// Behavioral regression: exercise shipped page scripts with transport/DOM doubles.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
async function main(){
  const timers=new Map(),calls=[],peers=[],sockets=[],nodes=new Map();let timerId=0,failOffer=false,micOpened=0,micStopped=0;
  const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',hidden:false,disabled:false,muted:true,srcObject:null,
    play:async()=>{},pause(){},classList:{toggle(){}},addEventListener(){},click(){return this.onclick?.();}});return nodes.get(selector);};
  const motion={...node('motion'),dataset:{motion:'welcome-wave'}};
  const modeButtons=['say','chat'].map(mode=>({...node(mode),dataset:{mode}}));
  const document={querySelector:node,querySelectorAll:s=>s==='[data-motion]'?[motion]:s==='[data-mode]'?modeButtons:[],addEventListener(){},activeElement:null};
  class PC{
    constructor(){this.connectionState='new';this.iceGatheringState='complete';peers.push(this);}
    addTransceiver(){}addEventListener(){}
    async createOffer(){return {type:'offer',sdp:'test'};}
    async setLocalDescription(d){this.localDescription=d;}
    async setRemoteDescription(){this.connectionState='connected';this.onconnectionstatechange?.();}
    close(){this.connectionState='closed';this.onconnectionstatechange?.();}
  }
  class WS{constructor(){this.readyState=1;sockets.push(this);}}
  class Recorder{
    static isTypeSupported(){return true;}
    constructor(){this.state='inactive';this.mimeType='audio/webm';}
    start(){this.state='recording';}stop(){this.state='inactive';this.onstop?.();}
  }
  const context=vm.createContext({console,AbortController,Blob,MediaRecorder:Recorder,
    navigator:{mediaDevices:{getUserMedia:async()=>{micOpened++;return {getTracks:()=>[{stop(){micStopped++;}}]};}}},
    document,window:{MediaRecorder:Recorder,addEventListener(){}},location:{host:'127.0.0.1:8766'},
    setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id),setInterval:()=>0,
    RTCPeerConnection:PC,MediaStream:class{addTrack(){}},WebSocket:WS,
    fetch:async(url,options={})=>{
      calls.push(url);
      if(url==='/api/offer'&&failOffer){failOffer=false;return {ok:false,text:async()=> 'temporarily unavailable'};}
      const result=url==='/api/health'?{model_state:'ready',rtc_connected:true,fay_connected:true,fay_core:true,provider:{configured:true},asr:{state:'ready'},speech:{provider:'bailian',voice:'Cherry'}}:
        url==='/api/offer'?{sdp:'answer',type:'answer',sessionid:'test'}:{ok:true,epoch:1};
      return {ok:true,json:async()=>result};
    }});
  const root=path.resolve(__dirname,'..');
  vm.runInContext(fs.readFileSync(path.join(root,'web/live.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'web/microphone.js'),'utf8'),context);
  const settle=async()=>{for(let i=0;i<35;i++)await Promise.resolve();};
  const emit=event=>sockets.at(-1).onmessage({data:JSON.stringify(event)});
  emit({event:'state',client_id:'current',playback_owner:'older-window',epoch:0});await settle();
  assert.equal(peers.length,1);assert.equal(peers.at(-1).connectionState,'connected');
  assert.equal(calls.filter(x=>x==='/api/offer').length,1,'Page opening must automatically establish exactly one stream');
  const retry=async()=>{const entry=[...timers].find(([,t])=>t.ms<=10000);assert.ok(entry,'Reconnect should be scheduled');timers.delete(entry[0]);entry[1].fn();await settle();};
  failOffer=true;peers.at(-1).connectionState='failed';peers.at(-1).onconnectionstatechange();await retry();
  assert.notEqual(peers.at(-1).connectionState,'connected');await retry();
  assert.equal(peers.at(-1).connectionState,'connected','A failed offer must retry without user input');
  emit({event:'playback_owner_changed',playback_owner:'new-window',epoch:1});await settle();
  const offers=calls.filter(x=>x==='/api/offer').length;
  await vm.runInContext('health()',context);await settle();
  assert.equal(calls.filter(x=>x==='/api/offer').length,offers,'An older window must not fight the new owner');
  node('#text').value='自动连接测试';await node('#send').onclick();await settle();
  assert.equal(peers.at(-1).connectionState,'connected');assert.ok(calls.includes('/api/chat'),'A question must automatically reclaim the stream');
  assert.ok(!calls.includes('/api/say')&&!calls.includes('/api/action'),'No public manual speech or gesture requests');
  peers.at(-1).connectionState='failed';peers.at(-1).onconnectionstatechange();await settle();
  await node('#record').onclick();await settle();
  assert.equal(micOpened,1,'Record must reconnect automatically and reach getUserMedia');
  assert.equal(node('#record').textContent,'结束录音并识别');
  await node('#cancel-record').onclick();await settle();assert.ok(micStopped>0);
  const html=fs.readFileSync(path.join(root,'web/live.html'),'utf8');
  assert.ok(!html.includes('id="connect"'),'Manual connection button must be removed');
  assert.ok(!/data-mode|data-motion|speech-action/.test(html),'Manual mode and action controls must be removed');
  assert.ok(!fs.readFileSync(path.join(root,'web/microphone.js'),'utf8').includes('请先连接实时展示'));
  console.log('PASS: open automatically, failed-offer retry, single-window ownership, command takeover, record reconnect, no manual connection button');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
