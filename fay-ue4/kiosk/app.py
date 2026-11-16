from __future__ import annotations
import asyncio
import contextlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from dotenv import set_key
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from .avatars import catalog
from .config import ROOT, Settings, api_key, data_root
from .fay_client import FayClient
from .knowledge import Knowledge, MAX_BYTES
from .providers import Bailian, ProviderError
from .session import Session
from .speech import SpeechCache
from .store import Store
from .tool_bridge import ToolBridge
from .microphone import Microphone


class Credentials(BaseModel):
    api_key: SecretStr


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def local_host(host):
    return host in ("localhost", "127.0.0.1", "::1", "testserver")


def create_app(root=None, provider_factory=Bailian, fay_factory=FayClient, bridge=None, microphone_factory=Microphone):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(Path(root) if root else data_root())
        app.state.knowledge = Knowledge(app.state.store)
        app.state.cache = SpeechCache(app.state.store)
        app.state.bridge = bridge or ToolBridge()
        app.state.session = None
        app.state.ws = None
        app.state.microphone = None
        app.state.connection_lock = asyncio.Lock()
        app.state.jobs = {}
        app.state.tasks = set()
        app.state.csrf = secrets.token_urlsafe(32)
        app.state.bridge_token = secrets.token_urlsafe(32)
        token_path = app.state.store.root / "bridge-token"
        token_path.write_text(app.state.bridge_token, encoding="ascii")
        yield
        if app.state.microphone:
            await app.state.microphone.close()
        if app.state.session:
            await app.state.session.close()
        for task in app.state.tasks:
            task.cancel()
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
        if token_path.exists() and token_path.read_text(encoding="ascii") == app.state.bridge_token:
            token_path.unlink()
        app.state.store.close()

    app = FastAPI(title="Fay + UE4 展示舱管理", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if not local_host(request.url.hostname):
            return JSONResponse({"detail": "仅限本机访问"}, 403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "拒绝跨站请求"}, 403)
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            return JSONResponse({"detail": "拒绝跨站请求"}, 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            expected = app.state.bridge_token if request.url.path.startswith("/internal/") else app.state.csrf
            header = "x-kiosk-bridge" if request.url.path.startswith("/internal/") else "x-kiosk-csrf"
            if not secrets.compare_digest(request.headers.get(header, ""), expected):
                return JSONResponse({"detail": "本机管理会话已失效，请刷新页面"}, 403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, 422)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 503)

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "web" / "index.html")

    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "fay-ue4-kiosk", "version": "0.1.0",
                "ai_configured": bool(api_key()), "ue_connected": app.state.session is not None,
                "fay_running": await fay_factory().health(), "offline_chat": False}

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {"csrf": app.state.csrf, "settings": app.state.store.settings.model_dump(),
                "avatars": [a.model_dump() for a in catalog(ROOT)]}

    @app.get("/api/settings")
    async def get_settings():
        return app.state.store.settings.model_dump()

    @app.put("/api/settings")
    async def settings(body: Settings):
        body.validate_consistency()
        if body.avatar_id not in {a.id for a in catalog(ROOT)}:
            raise ValueError("人物不在已安装目录中，请先导入并打包角色资产")
        app.state.store.save_settings(body)
        if app.state.microphone:
            await app.state.microphone.close()
            app.state.microphone = None
        if app.state.session:
            await app.state.session.reset()
            await start_microphone(app.state.session)
        return body.model_dump()

    @app.post("/api/credentials")
    async def credentials(body: Credentials):
        key = body.api_key.get_secret_value().strip()
        if not 10 <= len(key) <= 512 or any(c.isspace() for c in key):
            raise ValueError("密钥格式无效")
        set_key(str(ROOT / ".env.local"), "DASHSCOPE_API_KEY", key)
        os.environ["DASHSCOPE_API_KEY"] = key
        return {"ok": True, "message": "语音和向量密钥已保存；Fay 模型配置需同步后重启 Fay。"}

    @app.get("/api/documents")
    async def documents():
        return app.state.knowledge.documents()

    @app.post("/api/documents")
    async def upload(file: UploadFile = File(...), knowledge_base: str = Form("demo")):
        content = await file.read(MAX_BYTES + 1)
        await file.close()
        try:
            doc_id = await asyncio.to_thread(app.state.knowledge.insert, file.filename or "file.txt", knowledge_base, content)
        except ValueError:
            raise
        except Exception:
            raise HTTPException(422, "文档无法解析，请转为文字后重试") from None
        return {"id": doc_id, "ok": True}

    @app.delete("/api/documents/{doc_id}")
    async def delete_document(doc_id: str):
        # Cancel in-flight answers carrying a snapshot of the removed document.
        if app.state.session:
            await app.state.session.reset()
        app.state.knowledge.delete(doc_id)
        return {"ok": True}

    @app.post("/api/knowledge/index")
    async def index_knowledge():
        if app.state.jobs.get("index", {}).get("state") == "running":
            return app.state.jobs["index"]
        status = {"state": "running", "done": 0, "message": "正在建立索引"}
        app.state.jobs["index"] = status
        async def run():
            try:
                count = await app.state.knowledge.index(provider_factory(app.state.store.settings.ai))
                status.update(state="complete", done=count, message="索引已完成")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status.update(state="failed", message=str(exc) if isinstance(exc, ProviderError) else "索引失败，请检查配置")
        task = asyncio.create_task(run())
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return status

    @app.get("/api/jobs")
    async def jobs():
        return app.state.jobs

    @app.get("/api/events")
    async def events():
        return app.state.store.events()

    @app.post("/api/input")
    async def input_text(body: TextInput):
        if not app.state.session:
            raise HTTPException(409, "UE4 客户端尚未连接")
        await app.state.session.abort_capture()
        await app.state.session.submit(body.text, manual=True)
        return {"ok": True}

    @app.post("/api/interrupt")
    async def interrupt():
        if app.state.session:
            await app.state.session.stop("management")
            await app.state.session.abort_capture()
        return {"ok": True}

    @app.post("/internal/tools")
    async def tool(body: dict):
        return await app.state.bridge.execute(body.get("name"), body.get("arguments"))

    async def start_microphone(session):
        if not microphone_factory:
            return
        microphone = microphone_factory(session)
        try:
            await microphone.start()
            app.state.microphone = microphone
        except Exception:
            await microphone.close()
            await session.emit("notice", message="未能打开麦克风。仍可通过管理台文字调试；请检查音频设备和采样率。")

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        # Native renderer only. Browser management does not take over its session.
        if ws.headers.get("origin") or not local_host(ws.url.hostname):
            await ws.close(code=1008)
            return
        await ws.accept()
        async with app.state.connection_lock:
            if app.state.microphone:
                await app.state.microphone.close()
                app.state.microphone = None
            if app.state.session:
                with contextlib.suppress(Exception):
                    await app.state.session.close()
                with contextlib.suppress(Exception):
                    await app.state.ws.close(code=1000)
            session = Session(app.state.store, app.state.knowledge, app.state.cache,
                              app.state.bridge, ws.send_json, provider_factory, fay_factory())
            app.state.session, app.state.ws = session, ws
        await session.emit("hello", protocol=1, settings=app.state.store.settings.model_dump(),
                           avatars=[a.model_dump() for a in catalog(ROOT)])
        await start_microphone(session)
        try:
            while not session.closed:
                frame = await ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                if session.closed:
                    break
                try:
                    if frame.get("bytes") is not None:
                        if session.asr:
                            await session.asr.feed(frame["bytes"])
                        continue
                    raw = frame.get("text", "{}")
                    if len(raw) > 32000:
                        raise ValueError("请求过长")
                    msg = json.loads(raw)
                    if not isinstance(msg, dict):
                        raise ValueError("请求必须是对象")
                    kind = msg.get("type")
                    if kind == "text":
                        await session.abort_capture()
                        await session.submit(msg.get("text", ""), manual=True)
                    elif kind == "interrupt":
                        await session.stop("manual")
                        await session.abort_capture()
                    elif kind == "audio.start":
                        if app.state.microphone:
                            await app.state.microphone.manual_start()
                        else:
                            await session.begin_audio(msg.get("mode"))
                    elif kind == "audio.end":
                        if app.state.microphone:
                            await app.state.microphone.manual_end()
                        else:
                            await session.end_audio()
                    elif kind == "playback.complete":
                        session.ack(msg.get("turn_id"), msg.get("segment_id"))
                    elif kind == "metrics":
                        values = {k: float(msg[k]) for k in ("frame_ms_p95", "frame_ms_mean", "sample_seconds") if k in msg}
                        if len(values) == 3 and all(0 <= x <= 3600000 for x in values.values()):
                            app.state.store.log(session.id, "renderer_metrics", values)
                    elif kind == "client.error":
                        message = str(msg.get("message", "客户端错误"))[:500]
                        app.state.store.log(session.id, "client_error", {"message": message})
                        await session.stop("client_error")
                    else:
                        raise ValueError("不支持的客户端指令")
                except (ValueError, TypeError, ProviderError) as exc:
                    await session.emit("error", message=str(exc), fallback="service_unavailable")
        finally:
            with contextlib.suppress(Exception):
                await session.close()
            async with app.state.connection_lock:
                if app.state.session is session:
                    if app.state.microphone:
                        await app.state.microphone.close()
                        app.state.microphone = None
                    app.state.session, app.state.ws = None, None

    return app


app = create_app()
