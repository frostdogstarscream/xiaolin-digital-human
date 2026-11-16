"""Turn-scoped capabilities for Fay MCP tools; never execute late cancelled turns."""
import asyncio
import secrets
from .business import Business


class ToolBridge:
    def __init__(self, business=None):
        self.business = business or Business()
        self.leases = {}

    def register(self, session, turn):
        token = secrets.token_urlsafe(32)
        self.leases[token] = (session, turn, asyncio.Lock())
        return token

    def revoke(self, session):
        for token, (owner, _, _) in list(self.leases.items()):
            if owner is session:
                self.leases.pop(token, None)

    async def execute(self, name, arguments):
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "工具参数必须是对象。"}
        args = dict(arguments)
        token = args.pop("turn_token", None)
        if not isinstance(token, str) or token not in self.leases:
            return {"ok": False, "error": "对话已结束或授权已失效，未执行操作。"}
        session, turn, lock = self.leases[token]
        async with lock:
            if token not in self.leases or session.closed or turn != session.turn:
                return {"ok": False, "error": "对话已被打断，未执行操作。"}
            if session.tool_count >= 4:
                result = {"ok": False, "error": "本轮操作数量超过限制，请一次提出一个操作。"}
            else:
                session.tool_count += 1
                mapping = {"query_demo_status": "get_scene_status", "switch_demo_scene": "switch_scene"}
                result = await self.business.execute(mapping.get(name, ""), args, ["overview", "workflow", "value"])
            # In-flight writes may have reached the target even if the user interrupts.
            # Keep the audit record, but do not revive the old turn or its voice.
            session.store.log(session.id, "tool", {"name": name, "turn_id": turn, "result": result})
            if turn == session.turn and not session.closed:
                session.tool_results.append(result)
                await session.emit("tool.result", turn, name=name, result=result)
            return result


TOOLS = [
    {"name": "query_demo_status", "description": "查询展示系统当前主题及模拟设备统计。必须提供本轮 turn_token。",
     "inputSchema": {"type": "object", "properties": {"turn_token": {"type": "string"}},
                     "required": ["turn_token"], "additionalProperties": False}},
    {"name": "switch_demo_scene", "description": "切换展示主题。用户未明确主题时先追问；成功后按真实回执答复。",
     "inputSchema": {"type": "object", "properties": {"turn_token": {"type": "string"},
                     "scene_id": {"type": "string", "enum": ["overview", "workflow", "value"]}},
                     "required": ["turn_token", "scene_id"], "additionalProperties": False}},
]
