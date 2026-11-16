from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("AVATAR_HOME", str(Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1])))
load_dotenv(ROOT / ".env.local", override=False)


class Role(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=40)
    identity: str = Field(max_length=500)
    personality: str = Field(max_length=1000)
    answer_length: str = Field(default="简洁，通常不超过120字", max_length=200)
    greeting: str = Field(max_length=500)
    voice: str = Field(default="longxiaochun_v3", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    gesture_frequency: float = Field(default=0.5, ge=0, le=1)
    knowledge_base: str = Field(default="demo", pattern=r"^[a-z0-9_-]{1,40}$")


class DisplaySettings(BaseModel):
    monitor: int = Field(default=0, ge=0, le=7)
    fullscreen: bool = True
    avatar_scale: float = Field(default=1, ge=0.25, le=3)
    avatar_x: float = Field(default=0, ge=-3, le=3)
    avatar_y: float = Field(default=0, ge=-3, le=3)
    avatar_yaw: float = Field(default=0, ge=-180, le=180)
    brightness: float = Field(default=1, ge=0.3, le=2)
    subtitles: bool = False
    target_fps: int = Field(default=30, ge=15, le=60)


class AudioSettings(BaseModel):
    mode: str = Field(default="push_to_talk", pattern=r"^(push_to_talk|hands_free)$")
    microphone: str = Field(default="", max_length=200)
    # Unity uses the Windows default playback endpoint; switching is done in Windows.
    volume: float = Field(default=0.85, ge=0, le=1)
    vad_threshold: float = Field(default=0.025, ge=0.005, le=0.3)
    silence_ms: int = Field(default=650, ge=300, le=2000)
    aec_verified: bool = False


class AISettings(BaseModel):
    llm_model: str = Field(default="qwen-plus", min_length=1, max_length=100)
    asr_model: str = Field(default="fun-asr-realtime", min_length=1, max_length=100)
    tts_model: str = Field(default="cosyvoice-v3-flash", min_length=1, max_length=100)
    embedding_model: str = Field(default="text-embedding-v4", min_length=1, max_length=100)


class Settings(BaseModel):
    active_role: str = "reception"
    avatar_path: str = Field(default="", max_length=1000)
    roles: list[Role] = Field(min_length=1, max_length=20)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    ai: AISettings = Field(default_factory=AISettings)

    @property
    def role(self) -> Role:
        return next(r for r in self.roles if r.id == self.active_role)

    def validate_consistency(self):
        ids = [r.id for r in self.roles]
        if len(set(ids)) != len(ids) or self.active_role not in ids:
            raise ValueError("角色标识重复或当前角色不存在")
        if self.audio.mode == "hands_free" and not self.audio.aec_verified:
            raise ValueError("请先完成现场回声测试，再开启免按键模式")


def defaults() -> Settings:
    return Settings(roles=[
        Role(id="reception", name="亲切接待", identity="演示展厅的接待讲解员",
             personality="亲切自然，先理解来宾的问题，再清楚作答。", greeting="您好，欢迎体验数字人演示。您可以让我介绍项目，或者选择一个讲解主题。"),
        Role(id="formal", name="正式讲解", identity="项目演示讲解员",
             personality="正式稳重，条理清晰，使用准确的项目用语。", greeting="您好，我将为您介绍本次演示的项目概览、业务流程和应用价值。"),
        Role(id="technical", name="技术介绍", identity="数字人演示的技术讲解员",
             personality="专业务实，解释术语，区分已验证能力和演示数据。", answer_length="根据问题详细解释，通常不超过220字",
             greeting="您好，您可以向我了解这套演示的技术组成和工作流程。"),
    ])


def api_key() -> str:
    # Read at request time so the process never includes a key in serialized settings.
    return os.getenv("DASHSCOPE_API_KEY", "").strip()


def data_root() -> Path:
    return Path(os.getenv("AVATAR_DATA_DIR", str(ROOT / "runtime"))).resolve()
