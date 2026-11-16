import asyncio,json,time
from pathlib import Path
import aiohttp,numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription
URL='http://127.0.0.1:8773'
OUT=Path('/formal/validation.json')
async def main():
 events=[];frames=[];counts={'audio':0,'voiced':0};tasks=[];sizes=set()
 async with aiohttp.ClientSession(headers={'Origin':URL},trust_env=False,timeout=aiohttp.ClientTimeout(total=180)) as http:
  async def get():
   async with http.get(URL+'/api/health') as r:assert r.status==200;return await r.json()
  h=await get();assert (h['video_fps'],h['lipsync_backend'],h['precision'])==(50,'wav2lip','torch.float16'),h
  async with http.ws_connect(URL+'/ws?scope=formal50_validation',heartbeat=20) as ws:
   ready=await ws.receive_json();assert ready['type']=='ready';sid=ready['session_id']
   async def read():
    async for message in ws:
     if message.type==aiohttp.WSMsgType.TEXT:
      e=json.loads(message.data);events.append(e)
      if e['type'] in ('playing','playback_done','interrupted','error','listen_ready'):print('EVENT',e['type'],flush=True)
   reader=asyncio.create_task(read())
   async def wait(kind,start,timeout=70):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
     errors=[e for e in events[start:] if e['type']=='error'];assert not errors,errors
     found=next((e for e in events[start:] if e['type']==kind),None)
     if found:return found
     await asyncio.sleep(.1)
    raise TimeoutError(kind)
   pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
   @pc.on('track')
   def added(track):
    async def consume():
     try:
      while True:
       f=await track.recv()
       if track.kind=='video':frames.append(time.monotonic());sizes.add((f.width,f.height))
       else:
        counts['audio']+=1
        if np.max(np.abs(f.to_ndarray().astype(float)))>500:counts['voiced']+=1
     except Exception:pass
    tasks.append(asyncio.create_task(consume()))
   try:
    pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
    await pc.setLocalDescription(await pc.createOffer())
    async with http.post(URL+'/api/offer',headers={'X-Demo-Session':sid},json={'type':'offer','sdp':pc.localDescription.sdp}) as r:
     text=await r.text();assert r.status==200,text;answer=json.loads(text)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
    deadline=time.monotonic()+30
    while pc.connectionState!='connected':
     assert time.monotonic()<deadline,pc.connectionState
     await asyncio.sleep(.2)
    warm_deadline=time.monotonic()+45
    while len(frames)<100:
     assert time.monotonic()<warm_deadline,'Media warmup timeout'
     await asyncio.sleep(.2)
    start_time=time.monotonic()
    start=len(events);await ws.send_json({'type':'text','text':'请挥手欢迎我，只说“你好，欢迎你”。'})
    await wait('playing',start);await wait('playback_done',start)
    deadline=time.monotonic()+15
    while True:
     h=await get()
     if h['active_action']=='idle' and h['render_stats']['motion_frames']>=350:break
     assert time.monotonic()<deadline,h['render_stats'];await asyncio.sleep(.2)
    welcome=h['render_stats'].copy();print('WELCOME_350_FRAMES',flush=True)
    start=len(events);await ws.send_json({'type':'text','text':'请用十句话详细介绍你能提供哪些帮助。'})
    await wait('playing',start);mark=len(events);await ws.send_json({'type':'interrupt'});await wait('interrupted',mark,15)
    await asyncio.sleep(1);interrupted=await get();assert interrupted['audio_queue']==0,interrupted
    start=len(events);await ws.send_json({'type':'text','text':'只回复“好的”。'})
    await wait('playing',start);await wait('playback_done',start)
    start=len(events);await ws.send_json({'type':'listen'});await wait('listen_ready',start,10);await ws.send_json({'type':'stop'})
    while time.monotonic()-start_time<60:
     h=await get();assert h['render_error'] is None,h
     assert pc.connectionState=='connected',pc.connectionState
     await asyncio.sleep(1)
    finish=time.monotonic();received=[t for t in frames if start_time<=t<=finish]
    fps=(len(received)-1)/(received[-1]-received[0]);final=await get()
    full_window_fps=len(received)/(finish-start_time)
    max_gap=max(np.diff(received))
    assert full_window_fps>=47.5,(full_window_fps,fps)
    assert max_gap<1.0,max_gap
    assert sizes=={(1080,1920)},sizes
    assert counts['voiced']>0,counts
    assert final['render_error'] is None and final['audio_queue']==0,final
    report={'status':'PASSED','duration_seconds':finish-start_time,'received_fps':fps,'full_window_fps':full_window_fps,'max_video_gap_seconds':float(max_gap),'received_frames':len(received),'audio':counts,'dimensions':list(sizes),'video_fps':h['video_fps'],'precision':h['precision'],'welcome_stats':welcome,'final_stats':final['render_stats'],'interrupt_queue':interrupted['audio_queue'],'final_queue':final['audio_queue'],'wake_listener_ready':True,'events':events}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='events'}),flush=True)
   finally:
    await pc.close();reader.cancel()
    for task in tasks:task.cancel()
asyncio.run(main())

