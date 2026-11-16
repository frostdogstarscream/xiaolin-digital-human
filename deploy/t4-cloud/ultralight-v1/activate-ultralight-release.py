"""Atomically switch https://36.133.88.94:6444/ (xiaolin-nginx-1) onto validated
xiaolin-formal50-ultralight while preserving settings, memory, and 1-command rollback.
"""
import json
import subprocess
import urllib.request
from pathlib import Path

BASE = Path("/opt/xiaolin")
record = json.loads((BASE / "deployment/ultralight-release.json").read_text(encoding="utf-8"))
release = Path(record["release"])
port = record["port"]
prev_port = record["previous_port"]

validation = json.loads((release / "validation-ultralight.json").read_text(encoding="utf-8"))
assert validation["status"] == "PASSED"
assert all(
    validation["actions_completed"].get(name, 0) >= 1
    for name in ["welcome-wave", "goodbye-wave", "explain-open-palms", "acknowledge-nod"]
)

url_base = f"http://127.0.0.1:{port}"
with urllib.request.urlopen(url_base + "/api/health", timeout=5) as response:
    health = json.load(response)
assert health["status"] == "ready" and health["material_version"] == "rife-ultralight-v1", health

# Sync latest business switches from previous active release right before cutover
old_settings = Path(record["previous_release"]) / "state/settings.json"
settings = json.loads(old_settings.read_text(encoding="utf-8"))
settings.pop("revision", None)
settings["lipsync_backend"] = "wav2lip"
req = urllib.request.Request(
    url_base + "/api/settings",
    data=json.dumps(settings).encode("utf-8"),
    headers={"Content-Type": "application/json", "Origin": url_base},
    method="POST",
)
with urllib.request.urlopen(req, timeout=8) as response:
    assert response.status == 200

nginx = BASE / "releases/20261110-ports/deployment/nginx.conf"
source = nginx.read_text(encoding="utf-8")
old_directive = f"proxy_pass http://127.0.0.1:{prev_port};"
new_directive = f"proxy_pass http://127.0.0.1:{port};"
assert old_directive in source, f"Expected {old_directive} in nginx.conf"
nginx.write_text(source.replace(old_directive, new_directive), encoding="utf-8")

try:
    subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-t"], check=True)
    subprocess.run(["docker", "update", "--restart=unless-stopped", record["container"]], check=True)
    subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-s", "reload"], check=True)
except Exception:
    nginx.write_text(source, encoding="utf-8")
    subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-s", "reload"], check=True)
    subprocess.run(["docker", "update", "--restart=no", record["container"]], check=True)
    raise

control = BASE / "deployment/control-current.sh"
control.write_text(
    control.read_text(encoding="utf-8").replace(record["previous_container"], record["container"]),
    encoding="utf-8",
)

subprocess.run(["docker", "update", "--restart=no", record["previous_container"]], check=True)
subprocess.run(["docker", "stop", "-t", "45", record["previous_container"]], check=True)

runtime_path = BASE / "deployment/current-runtime.json"
runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
for key in ["retained", "retired"]:
    if isinstance(runtime.get(key), list):
        runtime[key] = [record["container"] if v == record["previous_container"] else v for v in runtime[key]]
runtime["retired"] = list(
    dict.fromkeys([v for v in runtime.get("retired", []) if v != record["container"]] + [record["previous_container"]])
)
runtime.update(
    formal_fps=50,
    formal_release=record["release"],
    formal_container=record["container"],
    formal_lipsync="wav2lip",
    lipsync_model="xiaolin-ultralight-v1",
    material_version="rife-ultralight-v1",
    graded_actions=4,
    bridge_seconds=0.4,
)
runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")

candidate = dict(
    release=record["release"],
    container=record["container"],
    candidate_port=port,
    fps=50,
    lipsync_backend="wav2lip",
    lipsync_model="xiaolin-ultralight-v1",
    precision="fp16",
    baseline=record["baseline"],
    material_version="rife-ultralight-v1",
)
(BASE / "deployment/formal50-candidate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
(release / "activated.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
print("FORMAL_6444_ULTRALIGHT_ACTIVATED", json.dumps(candidate))
