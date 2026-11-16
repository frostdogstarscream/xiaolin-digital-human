"""Installed/cooked character catalog. This does not import UE5 assets into UE4."""
import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import Any
from character_contract import validate_face, validate_motion


class Avatar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=80)
    actor_class: str = Field(pattern=r"^/(Game|Script)/[A-Za-z0-9_/.]+$")
    kind: str = Field(pattern=r"^(diagnostic|maya_fbx|metahuman_legacy)$")
    engine: str = "4.27.2"
    license_note: str = Field(min_length=1, max_length=2000)
    skeletal_mesh: str = Field(default="", pattern=r"^$|^/Game/[A-Za-z0-9_/.]+$")
    animations: dict[str, str] = Field(default_factory=dict)
    morphs: dict[str, str] = Field(default_factory=dict)
    face_driver: str = Field(default="morph", pattern=r"^(morph|bones)$")
    face_bones: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    motion_mode: str = Field(default="animations", pattern=r"^animations$")
    mesh_yaw: float = Field(default=0, ge=-180, le=180)
    mesh_scale: float = Field(default=1, gt=0, le=100)


def catalog(root: Path):
    path = root / "ue4" / "Content" / "Data" / "avatars.json"
    entries = [Avatar.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    if not entries or len({a.id for a in entries}) != len(entries):
        raise ValueError("角色目录为空或含重复标识")
    if any(a.engine != "4.27.2" for a in entries):
        raise ValueError("角色必须为 UE4.27.2 兼容资产，UE5 资产不能直接导入")
    for avatar in entries:
        if avatar.kind == "maya_fbx":
            if not avatar.skeletal_mesh:
                raise ValueError("Maya 人物必须配置骨骼网格")
            validate_face(avatar.model_dump())
            validate_motion(avatar.model_dump())
        import re
        if any(not re.fullmatch(r"/Game/[A-Za-z0-9_/.]+", p) for p in avatar.animations.values()):
            raise ValueError("动画必须是已打包的 /Game 资源路径")
    return entries
