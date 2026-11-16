import asyncio
import importlib.util
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from kiosk.app import create_app
from kiosk.avatars import catalog
from kiosk.business import Business
from kiosk.config import ROOT
from kiosk.fay_client import FayClient
from kiosk.knowledge import Knowledge
from kiosk.mcp_stdio import dispatch
from kiosk.providers import ProviderError
from kiosk.session import Session
from kiosk.speech import SpeechCache
from kiosk.store import Store
from kiosk.tool_bridge import ToolBridge


class FakeProvider:
    def __init__(self, settings): self.settings = settings
    async def embed(self, texts): return [[1., 0.] for _ in texts]
    async def tts(self, text, role): yield b'\x01\x00' * 100


class FakeFay:
    def __init__(self): self.calls = []; self.interruptions = []
    async def answer(self, user, prompt): self.calls.append((user, prompt)); return '这是测试回答。'
    async def interrupt(self, user): self.interruptions.append(user)
    async def health(self): return True


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.close()


async def make_session(store, fay=None, business=None, auto_ack=True):
    sent = []
    async def send(event):
        sent.append(event)
        if auto_ack and event['type'] == 'speech.end': session.ack(event['turn_id'], event['segment_id'])
    bridge = ToolBridge(business)
    session = Session(store, Knowledge(store), SpeechCache(store), bridge, send, FakeProvider, fay or FakeFay())
    return session, sent, bridge


async def test_wake_gate_stop_and_role_reset(store):
    session, sent, bridge = await make_session(store)
    try:
        await session.submit('旁边人的闲聊')
        assert not session.awake and session.task is None
        await session.submit('你好小慧')
        await session.task
        assert session.awake and any(e['type'] == 'speech.begin' for e in sent)
        await session.submit('项目是什么')
        await session.task
        assert len(session.fay.calls) == 1
        await session.submit('停止')
        assert session.task is None
        await session.reset()
        assert not session.awake and not session.history and not bridge.leases
    finally: await session.close()


async def test_idle_timer_clears_visitor_context(store):
    session, sent, _ = await make_session(store)
    try:
        session.awake = True
        session.history = [{'content': 'private'}]
        session.last_activity -= 31
        await asyncio.sleep(.6)
        assert not session.awake and not session.history
        assert any(e.get('state') == 'asleep' for e in sent)
    finally: await session.close()


async def test_cancel_revokes_late_tools_and_old_pcm(store):
    waiting = asyncio.Event()
    class SlowFay(FakeFay):
        async def answer(self, user, prompt):
            waiting.set()
            await asyncio.sleep(30)
            return '旧回答'
    requests = []
    async def transport(request):
        requests.append(request)
        return httpx.Response(200, json={'ok': True, 'simulation': True, 'scene_id': 'workflow'})
    session, sent, bridge = await make_session(store, SlowFay(), Business(httpx.MockTransport(transport)))
    try:
        await session.submit('切换到业务流程', manual=True)
        await waiting.wait()
        token = next(iter(bridge.leases))
        old_turn = session.turn
        await session.stop()
        result = await bridge.execute('switch_demo_scene', {'turn_token': token, 'scene_id': 'workflow'})
        assert not result['ok'] and not requests
        await session.emit('audio', old_turn, pcm='stale')
        assert not any(e.get('pcm') == 'stale' for e in sent)
    finally: await session.close()


async def test_tool_failure_overrides_fays_success_claim(store):
    async def transport(request): raise httpx.ReadTimeout('timeout')
    bridge = ToolBridge(Business(httpx.MockTransport(transport)))
    class ClaimFay(FakeFay):
        async def answer(self, user, prompt):
            token = next(iter(bridge.leases))
            result = await bridge.execute('switch_demo_scene', {'turn_token': token, 'scene_id': 'workflow'})
            assert result.get('unknown')
            return '已经成功切换。'
    session, sent, _ = await make_session(store, ClaimFay())
    session.bridge = bridge
    try:
        await session.submit('切换到业务流程', manual=True)
        await session.task
        answer = next(e['text'] for e in sent if e['type'] == 'answer')
        assert '结果未确认' in answer and '成功切换' not in answer
        assert not bridge.leases
    finally: await session.close()


async def test_playback_ack_must_match_current_turn_and_segment(store):
    session, sent, _ = await make_session(store, auto_ack=False)
    try:
        await session.submit('你好小慧')
        for _ in range(100):
            if any(e['type'] == 'speech.end' for e in sent): break
            await asyncio.sleep(.01)
        end = next(e for e in sent if e['type'] == 'speech.end')
        session.ack(end['turn_id'] - 1, end['segment_id'])
        assert not session.task.done()
        session.ack(end['turn_id'], end['segment_id'])
        await asyncio.wait_for(session.task, 1)
    finally: await session.close()


async def test_fay_native_sse_protocol_and_cancel_endpoint():
    calls = []
    async def handler(request):
        calls.append((request.url.path, json.loads(request.content or b'{}')))
        if request.url.path == '/v1/chat/completions':
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'status': True})
    fay = FayClient(httpx.MockTransport(handler))
    assert await fay.answer('visitor', 'question') == '你好'
    assert calls[0][1]['model'] == 'fay' and calls[0][1]['user'] == 'visitor'
    assert await fay.health()
    await fay.interrupt('visitor')
    assert calls[-2][0] == '/to-stop-talking' and calls[-1][0] == '/api/execution-cancel'


@pytest.mark.parametrize('body', ['data: {"choices":[{"delta":{"content":"半句"}}]}\n\n', 'data: {"error":"bad"}\n\n', 'data: [DONE]\n\n'])
async def test_fay_does_not_accept_incomplete_or_empty_output(body):
    fay = FayClient(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    with pytest.raises(ProviderError): await fay.answer('user', 'prompt')


def test_admin_csrf_aec_catalog_persistence_and_documents(tmp_path):
    app = create_app(tmp_path, FakeProvider, FakeFay, microphone_factory=None)
    with TestClient(app) as client:
        data = client.get('/api/bootstrap').json()
        headers = {'X-Kiosk-CSRF': data['csrf']}
        config = data['settings']
        assert client.put('/api/settings', json=config).status_code == 403
        assert client.get('/api/bootstrap', headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
        config['audio']['mode'] = 'hands_free'
        assert client.put('/api/settings', json=config, headers=headers).status_code == 422
        config['audio']['aec_verified'] = True
        config['avatar_id'] = 'diagnostic_compact'
        assert client.put('/api/settings', json=config, headers=headers).status_code == 200
        config['avatar_id'] = 'not-installed'
        assert client.put('/api/settings', json=config, headers=headers).status_code == 422
        result = client.post('/api/documents', files={'file': ('facts.md', '专属识别码是蓝色星辰。'.encode())}, data={'knowledge_base': 'private'}, headers=headers)
        assert result.status_code == 200
        doc_id = result.json()['id']
        assert client.delete('/api/documents/' + doc_id, headers=headers).status_code == 200
        assert all(d['id'] != doc_id for d in client.get('/api/documents').json())
        assert client.post('/api/input', json={'text': 'hello'}, headers=headers).status_code == 409
    assert not (tmp_path / 'bridge-token').exists()
    with TestClient(create_app(tmp_path, FakeProvider, FakeFay, microphone_factory=None)) as client:
        assert client.get('/api/settings').json()['avatar_id'] == 'diagnostic_compact'


def test_websocket_audio_and_reconnect_isolation(tmp_path):
    with TestClient(create_app(tmp_path, FakeProvider, FakeFay, microphone_factory=None)) as client:
        with client.websocket_connect('/ws') as ws:
            hello = ws.receive_json()
            assert hello['protocol'] == 1
            ws.send_json({'type': 'text', 'text': '介绍项目'})
            seen = []
            for _ in range(20):
                event = ws.receive_json(); seen.append(event['type'])
                if event['type'] == 'speech.end':
                    ws.send_json({'type': 'playback.complete', 'turn_id': event['turn_id'], 'segment_id': event['segment_id']})
                    break
            assert 'audio' in seen and 'sources' in seen
            with client.websocket_connect('/ws') as newer:
                new_hello = newer.receive_json()
                assert new_hello['session_id'] != hello['session_id']
                assert not client.app.state.bridge.leases


async def test_knowledge_isolation_and_deletion(store):
    kb = Knowledge(store)
    doc_id = kb.insert('秘密.md', 'private', '私有项目的识别码为翠蓝星河。'.encode())
    assert not any('翠蓝' in s['text'] for s in await kb.search('翠蓝星河', 'demo'))
    assert await kb.search('私有项目识别码', 'private')
    await kb.index(FakeProvider(store.settings.ai), 'private')
    assert (await kb.search('识别码', 'private', FakeProvider(store.settings.ai)))[0]['document'] == '秘密.md'
    kb.delete(doc_id)
    assert not await kb.search('识别码', 'private')


def test_mcp_protocol_and_unknown_tool():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'ok': True}))) as client:
        assert dispatch({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, client) is None
        init = dispatch({'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}}, client)
        assert init['result']['capabilities'] == {'tools': {}}
        tools = dispatch({'id': 2, 'method': 'tools/list'}, client)['result']['tools']
        assert {t['name'] for t in tools} == {'query_demo_status', 'switch_demo_scene'}
        failure = dispatch({'id': 3, 'method': 'tools/call', 'params': {'name': 'shell'}}, client)
        assert failure['result']['isError']


def test_maya_manifest_preflight(tmp_path):
    module_spec = importlib.util.spec_from_file_location('ue_import_character', ROOT / 'tools/ue_import_character.py')
    module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
    manifest = json.loads((ROOT / 'assets/character.example.json').read_text(encoding='utf-8'))
    path = tmp_path / 'character.json'; path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='FBX file missing'): module.validate_manifest(str(path))
    for f in ('character.fbx', 'idle.fbx', 'speaking.fbx', 'welcome.fbx'): (tmp_path / f).write_bytes(b'placeholder for path validation only')
    result = module.validate_manifest(str(path))
    assert Path(result['source_fbx']).is_absolute()
    manifest['morphs'].pop('jaw_open');path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Jaw'): module.validate_manifest(str(path))
    assert len(catalog(ROOT)) == 2
