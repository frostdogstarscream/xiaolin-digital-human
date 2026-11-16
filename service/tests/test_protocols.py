import asyncio
import json

import pytest
import httpx
from websockets.asyncio.server import serve

from service.config import AISettings, defaults
from service.providers import Bailian, ProviderError


async def test_streaming_tts_protocol(monkeypatch):
    observed = []
    async def server(ws):
        message = json.loads(await ws.recv())
        observed.append(message)
        await ws.send(json.dumps({"header": {"event": "task-started"}}))
        observed.append(json.loads(await ws.recv()))
        observed.append(json.loads(await ws.recv()))
        await ws.send(b"\x12\x00" * 20)
        await ws.send(b"\x10\x00" * 20)
        await ws.send(json.dumps({"header": {"event": "task-finished"}}))
    async with serve(server, "127.0.0.1", 0) as instance:
        port = instance.sockets[0].getsockname()[1]
        monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-credential")
        monkeypatch.setenv("DASHSCOPE_WS_URL", f"ws://127.0.0.1:{port}")
        provider = Bailian(AISettings())
        result = [frame async for frame in provider.tts("中文测试", defaults().role)]
    assert len(result) == 2
    assert [m["header"]["action"] for m in observed] == ["run-task", "continue-task", "finish-task"]
    assert observed[0]["payload"]["parameters"]["format"] == "pcm"
    assert observed[1]["payload"]["input"]["text"] == "中文测试"


async def test_streaming_asr_partial_final_and_finish(monkeypatch):
    partials = []
    observed = []
    async def partial(text):
        partials.append(text)
    async def server(ws):
        start = json.loads(await ws.recv())
        observed.append(start)
        await ws.send(json.dumps({"header": {"event": "task-started"}}))
        audio = await ws.recv()
        assert isinstance(audio, bytes)
        await ws.send(json.dumps({"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"text": "介绍一下", "sentence_end": False}}}}))
        finish = json.loads(await ws.recv())
        observed.append(finish)
        await ws.send(json.dumps({"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"text": "介绍一下项目", "sentence_end": True}}}}))
        await ws.send(json.dumps({"header": {"event": "task-finished"}}))
    async with serve(server, "127.0.0.1", 0) as instance:
        port = instance.sockets[0].getsockname()[1]
        monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-credential")
        monkeypatch.setenv("DASHSCOPE_WS_URL", f"ws://127.0.0.1:{port}")
        recognition = await Bailian(AISettings()).open_asr(partial)
        await recognition.feed(b"\x00\x00" * 320)
        text = await recognition.finish()
    assert text == "介绍一下项目"
    assert partials == ["介绍一下", "介绍一下项目"]
    assert observed[0]["header"]["task_id"] == observed[1]["header"]["task_id"]
    assert observed[0]["payload"]["parameters"]["sample_rate"] == 16000


async def test_provider_error_does_not_expose_remote_body(monkeypatch):
    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"header": {"event": "task-failed", "error_message": "private upstream detail"}}))
    async with serve(server, "127.0.0.1", 0) as instance:
        port = instance.sockets[0].getsockname()[1]
        monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-credential")
        monkeypatch.setenv("DASHSCOPE_WS_URL", f"ws://127.0.0.1:{port}")
        with pytest.raises(ProviderError) as error:
            _ = [chunk async for chunk in Bailian(AISettings()).tts("测试", defaults().role)]
        assert "private" not in str(error.value)


async def test_asr_failure_before_ready_closes_connection(monkeypatch):
    closed = asyncio.Event()
    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"header": {"event": "task-failed"}}))
        await ws.wait_closed()
        closed.set()
    async with serve(server, "127.0.0.1", 0) as instance:
        port = instance.sockets[0].getsockname()[1]
        monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-credential")
        monkeypatch.setenv("DASHSCOPE_WS_URL", f"ws://127.0.0.1:{port}")
        async def partial(text):
            pass
        with pytest.raises(ProviderError):
            await Bailian(AISettings()).open_asr(partial)
        await asyncio.wait_for(closed.wait(), 1)


async def test_truncated_llm_stream_never_yields_executable_tools(monkeypatch):
    import service.providers as module
    real_client = httpx.AsyncClient
    async def handler(request):
        delta = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call-1',
                 'function': {'name': 'switch_scene', 'arguments': '{"scene_id":"workflow"}'}}]}}]}
        return httpx.Response(200, text='data: ' + json.dumps(delta) + '\n\n')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'unit-test-credential')
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    events = []
    with pytest.raises(ProviderError, match='中断'):
        async for event in Bailian(AISettings()).chat([{'role': 'user', 'content': '测试'}]):
            events.append(event)
    assert not any(e.kind == 'tools' for e in events)
