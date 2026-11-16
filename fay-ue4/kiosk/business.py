import json
import os
import httpx


def definitions(chapters):
    ids = [c["id"] for c in chapters]
    mapping = "；".join(c["id"] + "=" + c["title"] for c in chapters)
    def tool(name, description, properties, required):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required,
                               "additionalProperties": False}}}
    return [
        tool("switch_scene", "切换演示系统的主题，不自动开始讲解。主题列表：" + mapping,
             {"scene_id": {"type": "string", "enum": ids}}, ["scene_id"]),
        tool("get_scene_status", "查询演示系统状态和模拟设备统计，结果必须说明是演示数据。", {}, []),
        tool("start_narration", "开始指定主题的固定讲解。主题列表：" + mapping,
             {"chapter_id": {"type": "string", "enum": ids}}, ["chapter_id"]),
        tool("control_narration", "暂停、继续、上一章或下一章固定讲解。",
             {"action": {"type": "string", "enum": ["pause", "resume", "previous", "next"]}}, ["action"]),
    ]


class Business:
    def __init__(self, transport=None):
        self.transport = transport
        self.base = os.getenv("FAY_KIOSK_DEMO_URL", "http://127.0.0.1:8781").rstrip("/")

    async def execute(self, name, arguments, scene_ids):
        try:
            params = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (ValueError, TypeError):
            return {"ok": False, "error": "接口参数格式错误，未执行操作。"}
        if not isinstance(params, dict):
            return {"ok": False, "error": "接口参数必须是对象，未执行操作。"}
        if name == "switch_scene":
            if set(params) != {"scene_id"} or params.get("scene_id") not in scene_ids:
                return {"ok": False, "error": "未指定有效主题，请先确认具体主题，未执行切换。"}
            method, path, body = "POST", "/scene/switch", params
        elif name == "get_scene_status" and not params:
            method, path, body = "GET", "/scene/status", None
        else:
            return {"ok": False, "error": "不支持的工具或参数，未执行操作。"}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=5, trust_env=False) as client:
                response = await client.request(method, self.base + path, json=body)
                if response.status_code != 200:
                    return {"ok": False, "error": "演示系统返回失败，未确认操作成功。"}
                result = response.json()
                if not isinstance(result, dict) or result.get("ok") is not True or result.get("simulation") is not True:
                    return {"ok": False, "error": "演示系统回执无效，未确认操作成功。"}
                if name == "switch_scene" and result.get("scene_id") != params["scene_id"]:
                    return {"ok": False, "error": "回执主题不一致，未确认切换成功。"}
                return result
        except httpx.TimeoutException:
            # Never retry writes blindly: request may have been applied remotely.
            return {"ok": False, "unknown": True, "error": "接口超时，结果未确认，请查询当前状态。"}
        except (httpx.HTTPError, ValueError):
            return {"ok": False, "error": "无法连接演示系统，未确认操作成功。"}
