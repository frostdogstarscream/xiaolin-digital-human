"""Receive real media twice, without model/TTS calls or attendance execution."""
import asyncio,json,time
from pathlib import Path
import aiohttp
from aiortc import RTCPeerConnection,RTCSessionDescription,RTCConfiguration

async def main():
    records=[]
    calls=Path('/shared/data/attendance-runtime/calls.jsonl')
    baseline=calls.read_bytes() if calls.exists() else b''
    async with aiohttp.ClientSession(trust_env=False) as http:
        for iteration in range(2):
            async with http.ws_connect('http://127.0.0.1:8766/ws') as ws:
                state=await ws.receive_json();owner=state['client_id']
                peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
                counts={'audio':0,'video':0};tasks=[]
                @peer.on('track')
                def track_added(track):
                    async def receive():
                        try:
                            while True:
                                await track.recv();counts[track.kind]+=1
                        except Exception:pass
                    tasks.append(asyncio.create_task(receive()))
                peer.addTransceiver('audio',direction='recvonly');peer.addTransceiver('video',direction='recvonly')
                started=time.monotonic()
                try:
                    await peer.setLocalDescription(await peer.createOffer())
                    async with http.post('http://127.0.0.1:8766/api/offer',
                        json={'type':'offer','sdp':peer.localDescription.sdp},
                        headers={'X-Avatar-Client':'1','X-Avatar-Viewer':owner}) as response:
                        assert response.status==200
                        answer=await response.json()
                    await peer.setRemoteDescription(RTCSessionDescription(type=answer['type'],sdp=answer['sdp']))
                    deadline=time.monotonic()+45
                    while counts['video']<35 or counts['audio']<20:
                        assert time.monotonic()<deadline,(peer.connectionState,counts)
                        await asyncio.sleep(.1)
                    records.append(dict(iteration=iteration+1,state=peer.connectionState,frames=dict(counts),seconds=round(time.monotonic()-started,3)))
                finally:
                    await peer.close()
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
            await asyncio.sleep(1)
    assert (calls.read_bytes() if calls.exists() else b'')==baseline
    report=dict(status='PASSED',scope='server-local WebRTC receivers',reconnect_did_not_execute=True,connections=records)
    Path('/app/deployment/reconnect-check.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
asyncio.run(main())
