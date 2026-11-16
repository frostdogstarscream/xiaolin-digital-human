from pathlib import Path
import shutil
p=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2/gateway_musetalk.py')
s=p.read_text();shutil.copy2(p,p.with_suffix('.py.before-turn-loopback'))
old='    cloud_runtime.configure_rtc()'
assert s.count(old)==1
s=s.replace(old,old+"\n    from turn_loopback import configure as configure_turn_loopback\n    configure_turn_loopback(os.environ['XIAOLIN_TURN_HOST'],os.environ['XIAOLIN_BIND_IP'])")
s=s.replace("request.query.get('takeover')=='1' and request.headers.get('X-Xiaolin-User')", "request.query.get('takeover')=='1' and request.headers.get('Origin') in ALLOWED")
p.write_text(s)
