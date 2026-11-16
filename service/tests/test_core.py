import asyncio
import io
import json

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from service.app import create_app
from service.business import Business
from service.config import defaults
from service.demo import create_app as demo_app
from service.knowledge import Knowledge, extract
from service.providers import ModelEvent, ProviderError
from service.session import Session
from service.speech import SpeechCache
from service.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path)
    yield result
    result.close()


class FakeAI:
    def __init__(self, settings):
        self.settings = settings

    async def embed(self, texts):
        return [[1., 0., 0.] for _ in texts]

    async def tts(self, text, role):
        yield b"\x01\x00" * 240

    async def chat(self, messages, tools=None):
        yield ModelEvent("text", "这是一条有测试标记的回答。")


def test_settings_persist_and_no_secret(tmp_path):
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        config = client.get("/api/settings").json()
        config["roles"][0]["name"] = "测试接待"
        assert client.put("/api/settings", json=config).status_code == 200
        assert "api_key" not in client.get("/api/settings").text.lower()
        assert client.get("/api/settings", headers={"Origin": "https://hostile.invalid"}).status_code == 403
        config["active_role"] = "missing"
        assert client.put("/api/settings", json=config).status_code == 422
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        assert client.get("/api/settings").json()["roles"][0]["name"] == "测试接待"


def test_aec_gate(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        config = client.get("/api/settings").json()
        config["audio"]["mode"] = "hands_free"
        assert client.put("/api/settings", json=config).status_code == 422
        config["audio"]["aec_verified"] = True
        assert client.put("/api/settings", json=config).status_code == 200


def test_document_formats_and_scanned_pdf():
    assert "中文" in extract("a.txt", "中文".encode("gb18030"))
    doc = Document()
    doc.add_paragraph("文档测试")
    doc.add_table(1, 1).cell(0, 0).text = "表格事实"
    stream = io.BytesIO()
    doc.save(stream)
    assert "表格事实" in extract("a.docx", stream.getvalue())
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    pdf.write(stream)
    with pytest.raises(ValueError, match="扫描"):
        extract("a.pdf", stream.getvalue())
    with pytest.raises(ValueError):
        extract("a.exe", b"anything")


async def test_knowledge_isolation_dedupe_and_sources(store):
    knowledge = Knowledge(store)
    data = "私有项目的专属识别码是星辰蓝。".encode()
    first = knowledge.insert("private.md", "private", data)
    assert knowledge.insert("copy.md", "private", data) == first
    assert not any("星辰蓝" in s["text"] for s in await knowledge.search("星辰蓝", "demo"))
    sources = await knowledge.search("专属识别码", "private")
    assert sources[0]["document"] == "private.md"
    assert sources[0]["chunk_id"]
    knowledge.delete(first)
    assert not await knowledge.search("专属识别码", "private")


async def test_tools_require_success_receipt():
    async def okay(request):
        return httpx.Response(200, json={"ok": True, "simulation": True, "scene_id": "workflow"})
    business = Business(httpx.MockTransport(okay))
    assert not (await business.execute("switch_scene", '{"scene_id":"unknown"}', ["workflow"]))["ok"]
    assert (await business.execute("switch_scene", '{"scene_id":"workflow"}', ["workflow"]))["ok"]
    assert not (await business.execute("run_shell", {}, ["workflow"]))["ok"]
    async def timeout(request):
        raise httpx.ReadTimeout("secret remote detail must not escape")
    business = Business(httpx.MockTransport(timeout))
    result = await business.execute("switch_scene", {"scene_id": "workflow"}, ["workflow"])
    assert result["unknown"] and not result["ok"]
    assert "secret" not in str(result)


def test_demo_is_real_service_with_simulated_data(tmp_path):
    with TestClient(demo_app(tmp_path)) as client:
        assert client.post("/scene/switch", json={"scene_id": "value"}).json()["ok"]
        status = client.get("/scene/status").json()
        assert status["scene_id"] == "value" and status["simulation"]
        assert client.post("/scene/switch", json={"scene_id": "invalid"}).status_code == 422
        assert client.get("/scene/status").json()["scene_id"] == "value"


async def wait_until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(.005)
    raise AssertionError("Timed out waiting for event")


async def test_narration_progress_needs_playback_ack_and_ignores_stale_ack(store):
    events = []
    async def send(event):
        events.append(event)
    session = Session(store, Knowledge(store), SpeechCache(store), send, FakeAI)
    await session.narrate("start", "overview")
    await wait_until(lambda: any(e["type"] == "speech.end" for e in events))
    first = next(e for e in events if e["type"] == "speech.end")
    assert session.position["sentence"] == 0
    await session.stop()
    session.ack(first["turn_id"], first["segment_id"])
    assert session.position["sentence"] == 0
    events.clear()
    await session.narrate("resume")
    await wait_until(lambda: any(e["type"] == "speech.end" for e in events))
    second = next(e for e in events if e["type"] == "speech.end")
    session.ack(second["turn_id"], second["segment_id"])
    await wait_until(lambda: session.position["sentence"] == 1)
    await session.close()


async def test_cancelled_synthesis_never_publishes_partial_cache(store):
    cache = SpeechCache(store)
    class Slow(FakeAI):
        async def tts(self, text, role):
            yield b"\x01\x00" * 10
            await asyncio.sleep(30)
    ai = Slow(store.settings.ai)
    role = store.settings.role
    async def run():
        async for _ in cache.stream("中断测试", role, ai):
            pass
    task = asyncio.create_task(run())
    await asyncio.sleep(.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not cache.path("中断测试", role, ai.settings.tts_model).exists()
    assert not list((store.root / "audio").glob("*.part"))


async def test_complete_cache_works_without_network(store):
    cache = SpeechCache(store)
    ai, role = FakeAI(store.settings.ai), store.settings.role
    first = b"".join([p async for p in cache.stream("缓存测试", role, ai)])
    class Offline(FakeAI):
        async def tts(self, text, role):
            raise ProviderError("offline")
            yield b""
    second = b"".join([p async for p in cache.stream("缓存测试", role, Offline(store.settings.ai))])
    assert first == second
    role.speech_rate = 1.3
    with pytest.raises(ProviderError):
        _ = [p async for p in cache.stream("缓存测试", role, Offline(store.settings.ai))]


async def test_role_switch_cancels_and_clears_history(store):
    async def send(event):
        pass
    session = Session(store, Knowledge(store), SpeechCache(store), send, FakeAI)
    session.history = [{"role": "user", "content": "旧角色内容"}]
    await session.narrate("start", "overview")
    await session.reset()
    assert session.history == [] and session.task is None
    await session.close()


def test_websocket_protocol_and_invalid_requests(tmp_path):
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["settings"]["roles"]
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
            ws.send_json({"type": "narration", "action": "start", "chapter_id": "missing"})
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "narration", "action": "start", "chapter_id": "overview"})
            for _ in range(20):
                event = ws.receive_json()
                if event["type"] == "speech.end":
                    ws.send_json({"type": "playback.complete", "turn_id": event["turn_id"], "segment_id": event["segment_id"]})
                if event["type"] == "narration.progress":
                    assert event["position"]["sentence"] == 1
                    break
            else:
                raise AssertionError("No narration progress")


async def test_failed_tool_receipt_cannot_be_rewritten_as_success(store):
    class ToolAI(FakeAI):
        async def chat(self, messages, tools=None):
            yield ModelEvent("tools", [{
                "id": "test-call", "type": "function", "function": {
                    "name": "switch_scene", "arguments": '{"scene_id":"workflow"}'}}])
    class Unconfirmed:
        async def execute(self, *args):
            return {"ok": False, "unknown": True, "error": "接口超时，结果未确认。"}
    events = []
    async def send(event):
        events.append(event)
    session = Session(store, Knowledge(store), SpeechCache(store), send, ToolAI, Unconfirmed())
    await session.submit("切换到业务流程")
    await wait_until(lambda: any(e['type'] == 'speech.end' for e in events))
    assert next(e['text'] for e in events if e['type'] == 'answer') == "接口超时，结果未确认。"
    assert len([e for e in events if e['type'] == 'tool.result']) == 1
    await session.close()


def test_removed_demo_document_does_not_reappear(tmp_path):
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        assert client.delete('/api/documents/demo-seed').status_code == 200
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        assert client.get('/api/documents').json() == []


def test_replaced_connection_cannot_submit_another_turn(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with TestClient(create_app(tmp_path, FakeAI)) as client:
        with client.websocket_connect('/ws') as old:
            old.receive_json()
            with client.websocket_connect('/ws') as current:
                assert current.receive_json()['type'] == 'hello'
                assert old.receive_json()['type'] == 'notice'
                old.send_json({'type': 'greet'})
                with pytest.raises(WebSocketDisconnect):
                    old.receive_json()


async def test_greeting_uses_current_role_and_playback_ack(store):
    events = []
    async def send(event):
        events.append(event)
    session = Session(store, Knowledge(store), SpeechCache(store), send, FakeAI)
    await session.greet()
    await wait_until(lambda: any(e['type'] == 'speech.end' for e in events))
    begin = next(e for e in events if e['type'] == 'speech.begin')
    assert begin['text'] == store.settings.role.greeting
    assert begin['gesture'] == 'greet'
    assert not session.task.done()
    session.ack(begin['turn_id'], begin['segment_id'])
    await wait_until(lambda: session.task.done())
    await session.close()


async def test_hands_free_noise_does_not_stop_lips_before_confirmed_speech(store):
    partial_handler = None
    class RecognitionStub:
        async def close(self):
            pass
    class RecognitionAI(FakeAI):
        async def open_asr(self, callback):
            nonlocal partial_handler
            partial_handler = callback
            return RecognitionStub()
    settings = store.settings
    settings.audio.aec_verified = True
    store.save_settings(settings)
    events = []
    async def send(event):
        events.append(event)
    session = Session(store, Knowledge(store), SpeechCache(store), send, RecognitionAI)
    await session.narrate('start', 'overview')
    await wait_until(lambda: any(e['type'] == 'speech.end' for e in events))
    old_turn = session.turn
    events.clear()
    await session.begin_audio('hands_free')
    assert not any(e['type'] in ('state', 'playback.stop') for e in events)
    await partial_handler('嗯')
    assert session.turn == old_turn
    await partial_handler('你好')
    assert session.turn > old_turn
    assert any(e['type'] == 'playback.stop' for e in events)
    assert any(e['type'] == 'state' and e['state'] == 'listening' for e in events)
    await session.close()
