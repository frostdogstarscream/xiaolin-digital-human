"""Small stdio MCP server for Fay. stdout is exclusively newline JSON-RPC.

Launch via python -m kiosk.mcp_stdio from this project's root. It forwards only
two registered tools to the running loopback service; no shell/URL execution.
"""
import json
import sys
import httpx
from .config import data_root
from .tool_bridge import TOOLS


def dispatch(request, client):
    method = request.get("method")
    if "id" not in request:
        return None
    reply = {"jsonrpc": "2.0", "id": request["id"]}
    if method == "initialize":
        offered = request.get("params", {}).get("protocolVersion")
        version = offered if offered in ("2024-11-05", "2025-03-26", "2025-06-18") else "2024-11-05"
        reply["result"] = {"protocolVersion": version, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "fay-ue4-kiosk", "version": "0.1.0"}}
    elif method == "ping":
        reply["result"] = {}
    elif method == "tools/list":
        reply["result"] = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            params = request.get("params", {})
            if params.get("name") not in {t["name"] for t in TOOLS}:
                raise ValueError("未注册的工具")
            token = (data_root() / "bridge-token").read_text(encoding="ascii").strip()
            response = client.post("http://127.0.0.1:8780/internal/tools", json=params,
                                   headers={"X-Kiosk-Bridge": token})
            response.raise_for_status()
            result = response.json()
        except (OSError, ValueError, httpx.HTTPError):
            result = {"ok": False, "error": "展厅接口未连接，操作结果未确认。"}
        reply["result"] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                           "isError": not result.get("ok", False)}
    else:
        reply["error"] = {"code": -32601, "message": "Method not found"}
    return reply


def main():
    with httpx.Client(timeout=8, trust_env=False) as client:
        for line in sys.stdin.buffer:
            try:
                if len(line) > 65536:
                    raise ValueError("oversized request")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("invalid request")
                reply = dispatch(request, client)
            except (ValueError, TypeError):
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if reply:
                sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
