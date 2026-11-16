from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from contextlib import asynccontextmanager

from dotenv import set_key
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from .config import ROOT, Settings, api_key, data_root
from .knowledge import Knowledge, MAX_BYTES
from .providers import Bailian, ProviderError
from .session import Session
from .speech import SpeechCache
from .store import Store


class Chapter(BaseModel):
    id: str = Field(pattern=r"^(overview|workflow|value)$")
    title: str = Field(min_length=1, max_length=40)
    sentences: list[str] = Field(min_length=1, max_length=100)


class Credentials(BaseModel):
    api_key: SecretStr


def create_app(root=None, provider_factory=Bailian):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(root or data_root())
        app.state.knowledge = Knowledge(app.state.store)
        app.state.cache = SpeechCache(app.state.store)
        app.state.sessions = set()
        app.state.jobs = {}
        app.state.tasks = set()
        yield
        for session in list(app.state.sessions):
            await session.close()
        for task in list(app.state.tasks):
            task.cancel()
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
        app.state.store.close()

    app = FastAPI(title="全息仓数字人本地服务", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Reject web pages trying to control the kiosk through localhost.
        if request.headers.get("origin") or request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            return JSONResponse({"detail": "仅接受本机原生客户端请求"}, status_code=403)
        if request.url.hostname not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return JSONResponse({"detail": "无效的本地服务地址"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(ProviderError)
    async def provider_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.get("/health")
    def health():
        return {"ok": True, "service": "avatar-kiosk", "version": "0.1.0",
                "ai_configured": bool(api_key()), "offline_chat": False}

    @app.get("/api/settings")
    def get_settings():
        return app.state.store.settings.model_dump()

    @app.put("/api/settings")
    async def save_settings(body: Settings):
        body.validate_consistency()
        app.state.store.save_settings(body)
        for session in list(app.state.sessions):
            await session.reset()
        return body.model_dump()

    @app.post("/api/credentials")
    async def save_credentials(body: Credentials):
        key = body.api_key.get_secret_value().strip()
        if not 10 <= len(key) <= 512 or any(c.isspace() for c in key):
            raise ValueError("密钥格式无效，请重新粘贴")
        # Explicit admin action from a password field. Never return the key.
        env_path = ROOT / ".env.local"
        set_key(str(env_path), "DASHSCOPE_API_KEY", key)
        os.environ["DASHSCOPE_API_KEY"] = key
        return {"ok": True, "ai_configured": True}

    @app.get("/api/chapters")
    def chapters():
        return app.state.store.get("chapters")

    @app.put("/api/chapters")
    async def save_chapters(body: list[Chapter]):
        if len(body) != 3 or {c.id for c in body} != {"overview", "workflow", "value"}:
            raise ValueError("首版须保留三个主题标识：overview、workflow、value")
        if any(not s.strip() or len(s) > 300 for c in body for s in c.sentences):
            raise ValueError("每句讲解须为1至300字")
        for session in list(app.state.sessions):
            await session.stop("chapter_update")
            session.position = {"chapter": body[0].id, "sentence": 0}
        app.state.store.set("chapters", [c.model_dump() for c in body])
        app.state.store.set("narration", {"chapter": body[0].id, "sentence": 0})
        return {"ok": True}

    @app.get("/api/documents")
    def documents():
        return app.state.knowledge.documents()

    @app.post("/api/documents")
    async def upload(file: UploadFile = File(...), knowledge_base: str = Form("demo")):
        content = await file.read(MAX_BYTES + 1)
        await file.close()
        try:
            doc_id = await asyncio.to_thread(app.state.knowledge.insert, file.filename or "document.txt", knowledge_base, content)
        except ValueError:
            raise
        except Exception:
            raise HTTPException(422, "文件无法解析，请检查格式或转换成TXT后导入") from None
        return {"ok": True, "id": doc_id, "indexed": False, "message": "原文已导入，可点击建立知识索引。"}

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: str):
        app.state.knowledge.delete(doc_id)
        return {"ok": True}

    def start_job(name, runner):
        if app.state.jobs.get(name, {}).get("state") == "running":
            return app.state.jobs[name]
        status = {"state": "running", "done": 0, "total": 0, "message": "正在处理"}
        app.state.jobs[name] = status
        async def run():
            try:
                await runner(status)
                status.update(state="complete", message="已完成")
            except asyncio.CancelledError:
                status.update(state="cancelled", message="任务已停止")
                raise
            except Exception as exc:
                status.update(state="failed", message=str(exc) if isinstance(exc, (ProviderError, ValueError)) else "任务失败，请检查网络和配置。")
        task = asyncio.create_task(run())
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return status

    @app.post("/api/knowledge/index")
    async def index():
        async def run(status):
            count = await app.state.knowledge.index(provider_factory(app.state.store.settings.ai))
            status.update(done=count, total=count)
        return start_job("index", run)

    @app.post("/api/cache/prepare")
    async def prepare_cache():
        async def run(status):
            settings = app.state.store.settings
            await app.state.cache.prepare(app.state.store.get("chapters"), settings.roles,
                                          provider_factory(settings.ai), status)
        return start_job("cache", run)

    @app.get("/api/cache")
    def cache():
        settings = app.state.store.settings
        return app.state.cache.inventory(app.state.store.get("chapters"), settings.roles, settings.ai.tts_model)

    @app.get("/api/jobs")
    def jobs():
        return app.state.jobs

    @app.get("/api/events")
    def events():
        return app.state.store.events()

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if ws.headers.get("origin") or ws.url.hostname not in ("127.0.0.1", "localhost", "::1", "testserver"):
            await ws.close(code=1008)
            return
        await ws.accept()
        # A kiosk has one foreground interactive client; reconnect supersedes the old client.
        for old in list(app.state.sessions):
            await old.emit("notice", message="另一个客户端已连接，此会话已结束。")
            await old.close()
        session = Session(app.state.store, app.state.knowledge, app.state.cache, ws.send_json, provider_factory)
        app.state.sessions.add(session)
        await session.emit("hello", settings=app.state.store.settings.model_dump(), chapters=app.state.store.get("chapters"),
                           ai_configured=bool(api_key()), narration=session.position)
        try:
            while not session.closed:
                frame = await ws.receive()
                if session.closed or frame["type"] == "websocket.disconnect":
                    break
                try:
                    if frame.get("bytes") is not None:
                        if session.asr:
                            await session.asr.feed(frame["bytes"])
                        continue
                    if len(frame.get("text", "")) > 32000:
                        raise ValueError("请求过长")
                    message = json.loads(frame.get("text", "{}"))
                    kind = message.get("type")
                    if kind == "text":
                        await session.abort_capture()
                        await session.submit(message.get("text", ""))
                    elif kind == "interrupt":
                        await session.stop("manual")
                        await session.abort_capture()
                    elif kind == "greet":
                        await session.abort_capture()
                        await session.greet()
                    elif kind == "narration":
                        await session.abort_capture()
                        await session.narrate(message.get("action", "start"), message.get("chapter_id"))
                    elif kind == "playback.complete":
                        session.ack(message.get("turn_id"), message.get("segment_id"))
                    elif kind == "audio.start":
                        await session.begin_audio(message.get("mode", "push_to_talk"))
                    elif kind == "audio.end":
                        await session.end_audio()
                    elif kind == "ping":
                        await session.emit("pong", at=time.time())
                    else:
                        raise ValueError("不支持的客户端指令")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await session.emit("error", message=str(exc) if isinstance(exc, (ValueError, ProviderError)) else "请求未完成，请检查连接并重试。")
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await session.close()
            app.state.sessions.discard(session)
            with contextlib.suppress(RuntimeError):
                await ws.close()

    return app


app = create_app()
