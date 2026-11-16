"""Adapt existing deployment acceptance harnesses to the Linux cloud release."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'runtime/server-4t4'
benchmark = (ROOT / 'runtime/deploy-1660/render-benchmark.py').read_text(encoding='utf-8')
start = benchmark.index('def memory_sample():')
end = benchmark.index('\ndef save():', start)
benchmark = benchmark[:start] + '''def memory_sample():
    import psutil
    memory = psutil.virtual_memory()
    return {'system_memory_used_MB': round((memory.total-memory.available)/1024**2, 2),
            'system_memory_available_MB': round(memory.available/1024**2, 2)}

''' + benchmark[end:]
benchmark = benchmark.replace("SMOKE_SECONDS = int(os.environ.get('RENDER_SMOKE_SECONDS', '0'))",
    "SMOKE_SECONDS = int(os.environ.get('RENDER_SMOKE_SECONDS', '0'))\nEXTERNAL = os.environ.get('RENDER_EXTERNAL_RECEIVER') == '1'\nREPORT['external_receiver'] = EXTERNAL")
start = benchmark.index('                pc = RTCPeerConnection(')
end = benchmark.index("                auth = {'X-Avatar-TTS':", start)
native = benchmark[start:end]
external = '''                if EXTERNAL:
                    deadline = time.monotonic() + 180
                    while not (bridge.presenter and bridge.rtc and any(p.connectionState == 'connected' for p in bridge.rtc.pcs)):
                        if time.monotonic() > deadline:
                            raise RuntimeError('External browser receiver did not connect')
                        await asyncio.sleep(.2)
                    headers['X-Avatar-Viewer'] = bridge.playback_owner
                else:
'''
benchmark = benchmark[:start] + external + ''.join('    ' + line if line.strip() else line for line in native.splitlines(keepends=True)) + benchmark[end:]
benchmark = benchmark.replace("'received_fps': round((final_received - first_received) / elapsed, 3),",
    "'received_fps': None if EXTERNAL else round((final_received - first_received) / elapsed, 3),")
benchmark = benchmark.replace("'seconds': round(elapsed, 3),", "'seconds': round(elapsed, 3), 'started_at': time.time() - (time.monotonic() - started),")
benchmark = benchmark.replace("deadline = time.monotonic() + 20\n                while not SMOKE_SECONDS", "deadline = time.monotonic() + 60\n                while not SMOKE_SECONDS")
benchmark = benchmark.replace("REPORT['sustained']['received_fps'] >= 24\n                    and REPORT['sustained']['queue_last_minute_max'] < 100",
    "REPORT['sustained']['render_fps'] >= 24.9\n                    and REPORT['sustained']['queue_last_minute_max'] <= 50\n                    and REPORT['sustained']['drain_seconds'] <= 2")
(WORK / 'render-benchmark.py').write_text(benchmark, encoding='utf-8')

live = (ROOT / 'runtime/deploy-1660/check_live.target.py').read_text(encoding='utf-8')
live = live.replace("ROOT=Path(__file__).resolve().parent;BASE=", "ROOT=Path('/app/attendance-mcp');BASE=")
start = live.index('async def control(script):')
end = live.index('\nasync def main(', start)
live = live[:start] + '''async def control(script):
    import sys
    operation = 'stop' if script.startswith('Stop') else 'start'
    if operation == 'stop':
        registration = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/'manage.py'), '--disable', stdout=asyncio.subprocess.DEVNULL)
        assert await registration.wait() == 0
    process = await asyncio.create_subprocess_exec('docker', operation, 'xiaolin-attendance-1', stdout=asyncio.subprocess.DEVNULL)
    assert await process.wait() == 0
    if operation == 'start':
        await asyncio.sleep(3)
        registration = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/'manage.py'), stdout=asyncio.subprocess.DEVNULL)
        assert await registration.wait() == 0

''' + live[end:]
live = live.replace('1660部署验证通过', '小霖云端部署验证通过')
(WORK / 'check_live.py').write_text(live, encoding='utf-8')
print('Prepared Linux render and real-provider integration harnesses')
