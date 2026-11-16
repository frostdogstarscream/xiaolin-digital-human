from pathlib import Path
p=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2/gateway_musetalk.py')
s=p.read_text()
old="                print('RTC_DIAG '+json.dumps(entry),flush=True)"
new="""                from aiortc.sdp import SessionDescription
                media=SessionDescription.parse(data.get('sdp',''))
                entry['media']=[dict(kind=m.kind,mid=m.rtp.muxId,port=m.port,candidates=len(m.ice_candidates),end=m.ice_candidates_complete) for m in media.media]
                entry['transports']=[dict(kind=t.kind,dtls=t.receiver.transport.state,ice=t.receiver.transport.transport.state,remote=[dict(kind=c.type,protocol=c.protocol) for c in t.receiver.transport.transport.getRemoteCandidates()]) for t in self.pc.getTransceivers()]
                print('RTC_DIAG '+json.dumps(entry),flush=True)"""
assert old in s;s=s.replace(old,new);p.write_text(s)
