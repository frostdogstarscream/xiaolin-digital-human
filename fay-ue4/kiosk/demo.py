"""Independent loopback-only demonstration business system."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .config import data_root
from .content import CHAPTERS
from .store import Store


class SwitchRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=40)


def create_app(root=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store((root or data_root()) / "demo-service")
        yield
        app.state.store.close()

    app = FastAPI(title="数字人演示接口（模拟数据）", lifespan=lifespan)

    def status():
        current = app.state.store.get("scene", "overview")
        return {"ok": True, "simulation": True, "scene_id": current,
                "scene_title": next(c["title"] for c in CHAPTERS if c["id"] == current),
                "status": "running", "statistics": {"online_devices": 12, "total_devices": 16},
                "notice": "以上为固定演示数据，不代表真实业务系统。"}

    @app.get("/health")
    def health():
        return {"ok": True, "service": "avatar-demo", "simulation": True}

    @app.get("/scene/status")
    def get_status():
        return status()

    @app.post("/scene/switch")
    def switch(body: SwitchRequest):
        if body.scene_id not in {c["id"] for c in CHAPTERS}:
            raise HTTPException(422, "未知演示主题，未执行切换")
        app.state.store.set("scene", body.scene_id)
        return status()

    return app


app = create_app()
