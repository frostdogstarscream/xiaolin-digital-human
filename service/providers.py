from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Awaitable

import httpx
from websockets.asyncio.client import connect

from .config import AISettings, Role, api_key


class ProviderError(Exception):
    """Safe, user-facing error; never include vendor response bodies or headers."""


def require_key():
    key = api_key()
    if not key:
        raise ProviderError("未配置百炼密钥，请在本机 .env.local 中配置 DASHSCOPE_API_KEY 并重启服务。")
    return key


def ws_url():
    return os.getenv("DASHSCOPE_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")


def task_message(action: str, task_id: str, payload: dict):
    return json.dumps({"header": {"action": action, "task_id": task_id, "streaming": "duplex"},
                       "payload": payload}, ensure_ascii=False)


@dataclass
class ModelEvent:
    kind: str
    value: object


class Bailian:
    def __init__(self, settings: AISettings):
        self.settings = settings

    async def chat(self, messages: list, tools: list | None = None) -> AsyncIterator[ModelEvent]:
        key = require_key()
        url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/") + "/chat/completions"
        body = {"model": self.settings.llm_model, "messages": messages, "stream": True,
                "temperature": 0.35, "max_tokens": 700, "enable_thinking": False}
        if tools:
            body.update(tools=tools, parallel_tool_calls=False)
        calls: dict[int, dict] = {}
        completed = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
                async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"}, json=body) as response:
                    if response.status_code != 200:
                        raise ProviderError(f"对话服务暂不可用（HTTP {response.status_code}），请检查账号、模型权限和网络。")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            completed = True
                            break
                        item = json.loads(data)
                        if "error" in item:
                            raise ProviderError("对话服务返回错误，请检查模型配置和额度。")
                        choices = item.get("choices") or []
                        if not choices:
                            continue
                        finish = choices[0].get("finish_reason")
                        if finish in ("length", "content_filter"):
                            raise ProviderError("回答未完整生成，请缩短问题后重试。")
                        if finish in ("stop", "tool_calls"):
                            completed = True
                        delta = choices[0].get("delta", {})
                        if delta.get("content"):
                            yield ModelEvent("text", delta["content"])
                        for call in delta.get("tool_calls", []):
                            current = calls.setdefault(call["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if call.get("id"):
                                current["id"] = call["id"]
                            for field in ("name", "arguments"):
                                current["function"][field] += call.get("function", {}).get(field, "")
            if not completed:
                raise ProviderError("对话响应中断，未执行未完成的操作，请重试。")
            if calls:
                yield ModelEvent("tools", [calls[i] for i in sorted(calls)])
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise ProviderError("无法连接对话服务或响应格式异常，请检查网络后重试。") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        key = require_key()
        url = os.getenv("DASHSCOPE_EMBEDDING_URL", "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding")
        result = []
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                for start in range(0, len(texts), 10):
                    batch = texts[start:start + 10]
                    response = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                        "model": self.settings.embedding_model, "input": {"texts": batch},
                        "parameters": {"dimension": 1024, "text_type": "document"},
                    })
                    if response.status_code != 200:
                        raise ProviderError(f"知识向量服务不可用（HTTP {response.status_code}）。")
                    values = response.json().get("output", {}).get("embeddings", [])
                    values.sort(key=lambda e: e["text_index"])
                    if len(values) != len(batch):
                        raise ProviderError("知识向量服务返回不完整结果。")
                    result.extend(v["embedding"] for v in values)
            return result
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderError("知识向量生成失败，已保留原文，可稍后重新建立索引。") from exc

    async def tts(self, text: str, role: Role) -> AsyncIterator[bytes]:
        key = require_key()
        task_id = uuid.uuid4().hex
        try:
            async with connect(ws_url(), additional_headers={"Authorization": f"Bearer {key}"},
                               open_timeout=10, max_size=4 * 1024 * 1024, ping_interval=20) as ws:
                await ws.send(task_message("run-task", task_id, {
                    "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
                    "model": self.settings.tts_model,
                    "parameters": {"text_type": "PlainText", "voice": role.voice, "format": "pcm",
                                   "sample_rate": 24000, "volume": 50, "rate": role.speech_rate, "pitch": 1},
                    "input": {},
                }))
                started = False
                while True:
                    frame = await asyncio.wait_for(ws.recv(), timeout=30)
                    if isinstance(frame, bytes):
                        if not started:
                            raise ProviderError("语音服务未正常启动。")
                        yield frame
                        continue
                    event = json.loads(frame).get("header", {}).get("event")
                    if event == "task-started":
                        started = True
                        await ws.send(task_message("continue-task", task_id, {"input": {"text": text}}))
                        await ws.send(task_message("finish-task", task_id, {"input": {}}))
                    elif event == "task-finished":
                        return
                    elif event == "task-failed":
                        raise ProviderError("语音合成失败，请检查所选音色、模型、地域和调用额度。")
        except (TimeoutError, OSError, ValueError) as exc:
            raise ProviderError("语音合成连接中断，请检查网络后重试。") from exc

    async def open_asr(self, on_partial: Callable[[str], Awaitable[None]]):
        return await Recognition.open(self.settings.asr_model, on_partial)


class Recognition:
    @classmethod
    async def open(cls, model, on_partial):
        self = cls()
        self.ws = await connect(ws_url(), additional_headers={"Authorization": f"Bearer {require_key()}"}, open_timeout=10)
        self.task_id = uuid.uuid4().hex
        self.on_partial = on_partial
        self.completed = []
        self.partial = ""
        self.done = asyncio.Event()
        self.ready = asyncio.Event()
        self.failure = None
        self.reader = asyncio.create_task(self._read())
        try:
            await self.ws.send(task_message("run-task", self.task_id, {
                "task_group": "audio", "task": "asr", "function": "recognition", "model": model,
                "parameters": {"format": "pcm", "sample_rate": 16000, "semantic_punctuation_enabled": False,
                               "max_sentence_silence": 650}, "input": {},
            }))
            await asyncio.wait_for(self.ready.wait(), 10)
            if self.failure:
                raise ProviderError(self.failure)
            return self
        except BaseException:
            await self.close()
            raise

    async def _read(self):
        try:
            async for frame in self.ws:
                if not isinstance(frame, str):
                    continue
                data = json.loads(frame)
                event = data.get("header", {}).get("event")
                if event == "task-started":
                    self.ready.set()
                elif event == "result-generated":
                    sentence = data.get("payload", {}).get("output", {}).get("sentence", {})
                    self.partial = sentence.get("text", "")
                    if self.partial:
                        await self.on_partial(self.partial)
                    if sentence.get("sentence_end") and self.partial:
                        self.completed.append(self.partial)
                        self.partial = ""
                elif event == "task-finished":
                    self.done.set()
                    return
                elif event == "task-failed":
                    self.failure = "语音识别失败，请检查模型权限、音频输入和网络。"
                    self.ready.set()
                    self.done.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failure = "语音识别连接中断，请重试。"
        finally:
            self.ready.set()
            self.done.set()

    async def feed(self, pcm):
        if self.failure:
            raise ProviderError(self.failure)
        if len(pcm) % 2 or len(pcm) > 64000:
            raise ValueError("音频帧必须为16位单声道PCM，且每帧不超过2秒")
        await self.ws.send(pcm)

    async def finish(self):
        try:
            await self.ws.send(task_message("finish-task", self.task_id, {"input": {}}))
            await asyncio.wait_for(self.done.wait(), 12)
            if self.failure:
                raise ProviderError(self.failure)
            return "".join(self.completed) + self.partial
        finally:
            await self.close()

    async def close(self):
        if self.reader is not asyncio.current_task():
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        await self.ws.close()
