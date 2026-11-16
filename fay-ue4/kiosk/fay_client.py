"""Fay's real `model=fay` API. No silent fallback to direct LLM calls."""
import asyncio
import json
import os
from urllib.parse import urlparse
import httpx
from .providers import ProviderError


class FayClient:
    def __init__(self, transport=None):
        self.base = os.getenv("FAY_KIOSK_FAY_URL", "http://127.0.0.1:5000").rstrip("/")
        parsed = urlparse(self.base)
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Fay 必须绑定本机 HTTP 地址")
        self.transport = transport

    async def answer(self, username, prompt):
        result = ""
        complete = False
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(90, connect=3), trust_env=False) as client:
                async with client.stream("POST", self.base + "/v1/chat/completions", json={
                    "model": "fay", "user": username, "stream": True,
                    "messages": [{"role": "user", "content": prompt}],
                }) as response:
                    if response.status_code != 200:
                        raise ProviderError(f"Fay 对话服务返回 HTTP {response.status_code}，请检查服务状态。")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            complete = True
                            break
                        obj = json.loads(payload)
                        if "error" in obj:
                            raise ProviderError("Fay 对话失败，请检查模型权限和配置。")
                        for choice in obj.get("choices", []):
                            result += choice.get("delta", {}).get("content") or ""
                            if choice.get("finish_reason") == "stop":
                                complete = True
                            elif choice.get("finish_reason") in ("length", "content_filter"):
                                raise ProviderError("Fay 回答未完整生成。")
                        if len(result) > 16000:
                            raise ProviderError("Fay 回答过长，已停止本轮。")
            if not complete or not result.strip():
                raise ProviderError("Fay 未返回完整回答，请重试。")
            return result.strip()
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("无法连接 Fay 或响应格式异常，请启动 Fay 后重试。") from exc

    async def interrupt(self, username):
        # UE playback is stopped independently; cancellation upstream is best effort.
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=2, trust_env=False) as client:
                await client.post(self.base + "/to-stop-talking", json={"username": username})
                await client.post(self.base + "/api/execution-cancel", json={"username": username})
        except httpx.HTTPError:
            pass

    async def health(self):
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=2, trust_env=False) as client:
                response = await client.post(self.base + "/api/get-run-status")
                return response.status_code == 200 and response.json().get("status") is True
        except (httpx.HTTPError, ValueError):
            return False
