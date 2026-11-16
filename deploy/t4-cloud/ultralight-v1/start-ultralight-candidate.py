"""Build material-cache on idle GPU 0 (if needed), start the candidate formal50-ultralight
container on port 8775, and wait for /api/health == ready.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

record = json.loads(Path("/opt/xiaolin/deployment/ultralight-release.json").read_text(encoding="utf-8"))
release = Path(record["release"])
info = json.loads((release / "previous-container.json").read_text(encoding="utf-8"))

# 1. Build RIFE 50fps + de-grin material cache on idle GPU 0 so live GPU 1 has zero extra load
if not (release / "material-cache/complete.json").exists():
    print("BUILDING_CACHE_ON_GPU0", record["build_gpu"], flush=True)
    build_cmd = [
        "docker", "run", "--rm", "--name", "xiaolin-ultralight-cache-builder",
        "--device", "nvidia.com/gpu=" + record["build_gpu"],
        "--shm-size", "2g",
        "-e", "HF_HUB_OFFLINE=1",
        "-e", "TRANSFORMERS_OFFLINE=1",
        "-e", "OMP_NUM_THREADS=4",
    ]
    for mount in info["Mounts"]:
        if mount["Destination"] != "/formal":
            build_cmd += ["-v", mount["Source"] + ":" + mount["Destination"] + ("" if mount["RW"] else ":ro")]
    build_cmd += [
        "-v", str(release) + ":/formal",
        "-w", "/formal/avatar-2d",
        info["Config"]["Image"],
        "python", "/formal/ultralight-assets/build-rife-ultralight-cache.py",
    ]
    subprocess.run(build_cmd, check=True)

assert (release / "material-cache/complete.json").exists(), "Material cache build incomplete"

# 2. Remove stale candidate container if re-running before activation
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
    "XIAOLIN_ULTRALIGHT_DIR=",
    "TRANSFORMERS_OFFLINE=",
)
for value in info["Config"]["Env"]:
    if not any(value.startswith(prefix) for prefix in overridden):
        args += ["-e", value]

for value in [
    f"QWEN_DEMO_PORT={record['port']}",
    "QWEN_STATE_DIR=/formal/state",
    "XIAOLIN_MATERIAL_CACHE=/formal/material-cache",
    "XIAOLIN_ULTRALIGHT_DIR=/formal/ultralight-assets",
    "TRANSFORMERS_OFFLINE=1",
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
                    "precision": health.get("precision"),
                }), flush=True)
                break
    except Exception:
        if time.monotonic() >= deadline:
            logs = subprocess.check_output(["docker", "logs", "--tail", "80", record["container"]], text=True, stderr=subprocess.STDOUT)
            raise RuntimeError(f"Candidate health timeout on {url}:\n{logs}")
    time.sleep(1.0)
