from pathlib import Path
import shutil
p=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2/gateway_musetalk.py')
shutil.copy2(p,p.with_suffix('.py.before-rtc-diagnostics'))
s=p.read_text()
old="            data,_=prepare_local_offer(data)"
new="""            import collections
            def rtc_diag(stage):
                offer_lines=data.get('sdp','').splitlines()
                candidates=[line.split() for line in offer_lines if line.startswith('a=candidate:')]
                entry=dict(at=time.time(),session=self.id,stage=stage,
                    candidates=[dict(protocol=c[2],kind=c[7],mdns=c[4].endswith('.local')) for c in candidates if len(c)>7],
                    connection=self.pc.connectionState,ice=self.pc.iceConnectionState,signaling=self.pc.signalingState)
                print('RTC_DIAG '+json.dumps(entry),flush=True)
                with (OUT/'rtc-diagnostics.jsonl').open('a') as log:log.write(json.dumps(entry)+'\\n')
            @self.pc.on('iceconnectionstatechange')
            async def ice_changed():rtc_diag('ice_state')
            @self.pc.on('connectionstatechange')
            async def connection_changed():rtc_diag('connection_state')
            rtc_diag('offer')
            data,_=prepare_local_offer(data)"""
assert old in s
s=s.replace(old,new)
s=s.replace("            return dict(type='answer',sdp=self.pc.localDescription.sdp)","            rtc_diag('answer')\n            return dict(type='answer',sdp=self.pc.localDescription.sdp)")
p.write_text(s)
