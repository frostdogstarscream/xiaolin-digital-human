"""Exercise the packaged service over real loopback HTTP/WebSocket, with isolated data."""
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import wave

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.store import Store
from service.speech import SpeechCache


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def main():
    exe = ROOT / 'dist/service-build/AvatarService/AvatarService.exe'
    assert exe.is_file()
    checks = []
    with tempfile.TemporaryDirectory(prefix='service-smoke-', dir=ROOT / 'runtime') as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to((ROOT / 'runtime').resolve())
        text = (ROOT / 'runtime/native-smoke/speech-test.txt').read_text(encoding='utf-8-sig')
        with wave.open(str(ROOT / 'runtime/native-smoke/speech-test.wav')) as wav:
            pcm = wav.readframes(wav.getnframes())
        store = Store(work)
        settings = store.settings
        settings.roles[0].voice = 'windows-huihui-test'
        settings.roles[0].greeting = text
        store.save_settings(settings)
        SpeechCache(store).path(text, settings.role, settings.ai.tts_model).write_bytes(pcm)
        store.close()
        env = dict(os.environ, AVATAR_HOME=str(work), DASHSCOPE_API_KEY='')
        ports = [free_port(), free_port()]
        processes = []
        logs = []
        try:
            for i, port in enumerate(ports):
                log = (work / f'process-{i}.log').open('w', encoding='utf-8')
                logs.append(log)
                processes.append(subprocess.Popen([str(exe), '--port', str(port), '--data-dir', str(work)] +
                    (['--demo'] if i else []), env=env, cwd=work, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW))
            async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                for i, port in enumerate(ports):
                    for attempt in range(60):
                        try:
                            health = (await client.get(f'http://127.0.0.1:{port}/health')).json()
                            assert health['service'] == ('avatar-demo' if i else 'avatar-kiosk')
                            break
                        except (httpx.HTTPError, ValueError):
                            await asyncio.sleep(.25)
                    else:
                        raise RuntimeError('Packaged service did not become healthy')
                checks.append('both_frozen_services_started')
                base = f'http://127.0.0.1:{ports[0]}'
                health = (await client.get(base + '/health')).json()
                assert not health['ai_configured']
                body = (await client.get(base + '/api/settings')).json()
                body['roles'][0]['name'] = '封装程序测试'
                assert (await client.put(base + '/api/settings', json=body)).status_code == 200
                assert (await client.get(base + '/api/settings')).json()['roles'][0]['name'] == '封装程序测试'
                checks.append('settings_write_read')
                response = await client.post(base + '/api/documents', data={'knowledge_base': 'smoke'},
                    files={'file': ('smoke.md', '测试知识库的标记是云杉蓝。'.encode(), 'text/markdown')})
                assert response.status_code == 200
                assert any(doc['kb'] == 'smoke' for doc in (await client.get(base + '/api/documents')).json())
                checks.append('knowledge_import')
                demo = f'http://127.0.0.1:{ports[1]}'
                assert (await client.post(demo + '/scene/switch', json={'scene_id': 'workflow'})).json()['ok']
                result = (await client.get(demo + '/scene/status')).json()
                assert result['simulation'] and result['scene_id'] == 'workflow'
                checks.append('demo_switch_status_http')
            async with connect(f'ws://127.0.0.1:{ports[0]}/ws', proxy=None) as ws:
                assert json.loads(await ws.recv())['type'] == 'hello'
                await ws.send(json.dumps({'type': 'greet'}))
                chunks = []
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    assert event['type'] != 'error', event
                    if event['type'] == 'audio':
                        chunks.append(base64.b64decode(event['pcm']))
                    if event['type'] == 'speech.end':
                        await ws.send(json.dumps({'type': 'playback.complete',
                            'turn_id': event['turn_id'], 'segment_id': event['segment_id']}))
                        break
                assert b''.join(chunks) == pcm
                while json.loads(await asyncio.wait_for(ws.recv(), 5)).get('state') != 'idle':
                    pass
                checks.append('cached_pcm_websocket_and_completion_ack')
        finally:
            for process in processes:
                process.terminate()
                process.wait(timeout=10)
            for log in logs:
                log.close()
    report = {'result': 'passed', 'checked_at_unix': time.time(), 'checks': checks,
              'cloud_calls': 0, 'audio': 'isolated Windows SAPI Chinese test; not Bailian',
              'note': 'Does not validate Unity rendering, real speakers, ASR or cloud model permissions.'}
    (ROOT / 'docs/service-smoke-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
