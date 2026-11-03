"""Reproduce an unresolved Firefox-style mDNS offer and verify real ICE/media."""
import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
from rtc_compat import prepare_local_offer
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription,AudioStreamTrack,VideoStreamTrack


async def main():
    config=RTCConfiguration(iceServers=[])
    client=RTCPeerConnection(config)
    bad=RTCPeerConnection(config)
    fixed=RTCPeerConnection(config)
    tracks={}
    @client.on('track')
    def on_track(track):tracks[track.kind]=track
    for peer in [bad,fixed]:
        peer.addTrack(AudioStreamTrack());peer.addTrack(VideoStreamTrack())
    try:
        client.addTransceiver('audio',direction='recvonly');client.addTransceiver('video',direction='recvonly')
        await client.setLocalDescription(await client.createOffer())
        original={'type':'offer','sdp':client.localDescription.sdp}
        same,changed=prepare_local_offer(original)
        assert not changed and same is original,'Normal IP candidates must remain unchanged'
        lines=[]
        for line in original['sdp'].splitlines():
            if line.startswith('a=candidate:'):
                parts=line.split();parts[4]='5a34778c-7434-4d1d-b86b-ded7a19c061e.local';line=' '.join(parts)
            lines.append(line)
        hidden={**original,'sdp':'\r\n'.join(lines)+'\r\n'}
        await bad.setRemoteDescription(RTCSessionDescription(**hidden))
        await bad.setLocalDescription(await bad.createAnswer())
        before=sum(line.startswith('a=candidate:') for line in bad.localDescription.sdp.splitlines())
        assert before==0,'Expected reproduction of premature candidate pruning'
        await bad.close()
        prepared,changed=prepare_local_offer(hidden)
        assert changed and 'a=end-of-candidates' not in prepared['sdp']
        await fixed.setRemoteDescription(RTCSessionDescription(**prepared))
        await fixed.setLocalDescription(await fixed.createAnswer())
        after=sum(line.startswith('a=candidate:') for line in fixed.localDescription.sdp.splitlines())
        assert after>0,'Server must retain usable host candidates'
        await client.setRemoteDescription(fixed.localDescription)
        deadline=asyncio.get_running_loop().time()+12
        while client.connectionState!='connected' or fixed.connectionState!='connected':
            assert asyncio.get_running_loop().time()<deadline,(client.connectionState,fixed.connectionState)
            await asyncio.sleep(.1)
        await asyncio.wait_for(tracks['audio'].recv(),5)
        await asyncio.wait_for(tracks['video'].recv(),5)
        report={'negative_control_candidates':before,'fixed_answer_candidates':after,
                'authenticated_peer_reflexive_ice_connected':True,'received_audio':True,'received_video':True,
                'normal_ip_offer_unchanged':True,'external_stun_turn':False,
                'browser_privacy_or_firewall_modified':False,'status':'REAL_MDNS_ICE_MEDIA_REGRESSION_PASSED'}
        (ROOT/'docs/mdns-compat-validation-v1.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True)
    finally:
        await asyncio.gather(client.close(),bad.close(),fixed.close())


if __name__=='__main__':asyncio.run(main())
