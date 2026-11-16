"""Verify the realtime dialogue endpoint with a real WebRTC receiver."""
import argparse,asyncio,json,ssl,time
from pathlib import Path
import aiohttp,numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCIceServer,RTCSessionDescription

async def main():
 parser=argparse.ArgumentParser();parser.add_argument('--url',default='https://36.133.88.94:6444');parser.add_argument('--output',required=True);parser.add_argument('--ca');args=parser.parse_args()
 origin=args.url;context=ssl.create_default_context(cafile=args.ca) if args.ca else None
 headers={'Origin':origin};events=[];counts={'video':0,'audio':0,'voiced':0};dims=set();tasks=[];pc=None
 async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=context),headers=headers,trust_env=False,timeout=aiohttp.ClientTimeout(total=150)) as http:
  async def get(route):
   async with http.get(origin+route) as r:
    assert r.status==200,(route,r.status)
    return await r.json()
  before=await get('/api/health');assert before.get('lipsync_backend')=='musetalk-1.5',before
  async with http.ws_connect(origin+'/ws?scope=musetalk_validation',heartbeat=20) as ws:
   ready=await ws.receive_json(timeout=15);assert ready['type']=='ready',ready
   sid=ready['session_id']
   async def reader():
    async for message in ws:
     if message.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(message.data))
   reader_task=asyncio.create_task(reader())
   config=await get('/api/rtc-config');pc=RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**x) for x in config['iceServers']]))
   @pc.on('track')
   def added(track):
    async def consume():
     try:
      while True:
       frame=await track.recv();counts[track.kind]+=1
       if track.kind=='video':dims.add((frame.width,frame.height))
       elif np.max(np.abs(frame.to_ndarray().astype(float)))>500:counts['voiced']+=1
     except Exception:pass
    tasks.append(asyncio.create_task(consume()))
   async def wait_event(kind,start=0,seconds=100):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
     errors=[x for x in events[start:] if x['type']=='error'];assert not errors,errors
     found=next((x for x in events[start:] if x['type']==kind),None)
     if found:return found
     await asyncio.sleep(.2)
    raise TimeoutError(kind)
   try:
    pc.addTransceiver('audio',direction='recvonly');pc.addTransceiver('video',direction='recvonly')
    await pc.setLocalDescription(await pc.createOffer())
    async with http.post(origin+'/api/offer',headers={'X-Demo-Session':sid},json={'type':'offer','sdp':pc.localDescription.sdp}) as r:
     text=await r.text();assert r.status==200,text;answer=json.loads(text)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
    deadline=time.monotonic()+30
    while pc.connectionState!='connected':
     assert time.monotonic()<deadline,pc.connectionState
     await asyncio.sleep(.2)
    start=len(events);await ws.send_json({'type':'text','text':'请挥手欢迎我，只说“你好，欢迎你”。'})
    await wait_event('playing',start);await wait_event('playback_done',start)
    first=await get('/api/health')
    start=len(events);await ws.send_json({'type':'text','text':'请详细介绍一下你能提供哪些帮助，说十句话。'})
    await wait_event('playing',start)
    marker=len(events);await ws.send_json({'type':'interrupt'});await wait_event('interrupted',marker,20)
    await asyncio.sleep(2);interrupted=await get('/api/health')
    start=len(events);await ws.send_json({'type':'text','text':'只回复“好的”。'})
    await wait_event('playing',start);await wait_event('playback_done',start)
    final=await get('/api/health')
    assert (1080,1920) in dims,dims
    assert counts['voiced']>0 and counts['video']>50,counts
    assert final['render_stats']['inference_frames']>0,final
    assert final['render_error'] is None,final
    assert final['audio_queue']==0,final['audio_queue']
    report={'status':'PASSED','url':origin,'lipsync_backend':final['lipsync_backend'],'decoder':final['lipsync_decoder'],'received':counts,'dimensions':list(dims),'first_turn_stats':first['render_stats'],'interrupt_queue':interrupted['audio_queue'],'final_queue':final['audio_queue'],'render_error':final['render_error'],'events':events}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False))
   finally:
    if pc:await pc.close()
    reader_task.cancel()
    for task in tasks:task.cancel()
asyncio.run(main())
