"""Start the blue-green candidate container xiaolin-formal50-dit-v2-fay on port 8775/8776
reusing the staged rife-dit-v2 material-cache and wait for /api/health == ready.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

record = json.loads(Path("/opt/xiaolin/deployment/dit-v2-fay-release.json").read_text(encoding="utf-8"))
release = Path(record["release"])
info = json.loads((release / "previous-container.json").read_text(encoding="utf-8"))

assert (release / "material-cache/complete.json").exists(), "Material cache incomplete"
assert (release / "dit-v2-assets/xiaolin_dit_student256_full_best.pth").exists(), "DiT-v2 weights missing"

subprocess.run(["docker", "rm", "-f", record["container"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

args = [
    "docker", "run", "-d",
    "--name", record["container"],
    "--restart", "no",
    "--network", "host",
    "--device", "nvidia.com/gpu=" + record["formal_gpu"],
    "--shm-size", "2g",
]
overridden = (
    "QWEN_DEMO_PORT=",
    "QWEN_STATE_DIR=",
    "XIAOLIN_MATERIAL_CACHE=",
    "XIAOLIN_DIT_V2_DIR=",
    "TRANSFORMERS_OFFLINE=",
    "XIAOLIN_FAY_URL=",
    "XIAOLIN_FAY_MCP_URL=",
    "XIAOLIN_FAY_WS_URL=",
)
for value in info["Config"]["Env"]:
    if not any(value.startswith(prefix) for prefix in overridden):
        args += ["-e", value]

for value in [
    f"QWEN_DEMO_PORT={record['port']}",
    "QWEN_STATE_DIR=/formal/state",
    "XIAOLIN_MATERIAL_CACHE=/formal/material-cache",
    "XIAOLIN_DIT_V2_DIR=/formal/dit-v2-assets",
    "TRANSFORMERS_OFFLINE=1",
    "XIAOLIN_FAY_URL=http://127.0.0.1:5000",
    "XIAOLIN_FAY_MCP_URL=http://127.0.0.1:5010",
    "XIAOLIN_FAY_WS_URL=ws://127.0.0.1:10002",
]:
    args += ["-e", value]

for mount in info["Mounts"]:
    if mount["Destination"] != "/formal":
        args += ["-v", mount["Source"] + ":" + mount["Destination"] + ("" if mount["RW"] else ":ro")]

args += [
    "-v", str(release) + ":/formal",
    "-w", "/formal/avatar-2d",
    info["Config"]["Image"],
    "python", "/formal/avatar-2d/experiments/qwen-realtime-v2/gateway50.py",
]
cid = subprocess.check_output(args, text=True).strip()
print("CANDIDATE_STARTED", cid, flush=True)

url = f"http://127.0.0.1:{record['port']}/api/health"
deadline = time.monotonic() + 120
while True:
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            health = json.load(resp)
            if health.get("status") == "ready":
                print("CANDIDATE_READY", json.dumps({
                    "port": record["port"],
                    "video_fps": health.get("video_fps"),
                    "material_version": health.get("material_version"),
                    "lipsync_model": health.get("lipsync_model"),
                    "persona_name": health.get("persona_name"),
                    "mcp_tool_count": health.get("mcp_tool_count"),
                    "dialogue_mode": health.get("dialogue_mode"),
                }, ensure_ascii=False), flush=True)
                break
    except Exception:
        if time.monotonic() >= deadline:
            logs = subprocess.check_output(["docker", "logs", "--tail", "80", record["container"]], text=True, stderr=subprocess.STDOUT)
            raise RuntimeError(f"Candidate health timeout on {url}:\n{logs}")
    time.sleep(1.0)
