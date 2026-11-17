"""1-command rollback from xiaolin-formal50-dit-v2-fay to the previous formal 50 fps container."""
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path("/opt/xiaolin")
record = json.loads((BASE / "deployment/dit-v2-fay-release.json").read_text(encoding="utf-8"))
release = Path(record["release"])

subprocess.run(["docker", "update", "--restart=unless-stopped", record["previous_container"]], check=True)
subprocess.run(["docker", "start", record["previous_container"]], check=True)

prev_health_url = f"http://127.0.0.1:{record['previous_port']}/api/health"
deadline = time.monotonic() + 90
while True:
    try:
        with urllib.request.urlopen(prev_health_url, timeout=3) as response:
            if json.load(response).get("status") == "ready":
                break
    except Exception:
        if time.monotonic() >= deadline:
            raise
    time.sleep(1.0)

shutil.copyfile(release / "previous-nginx.conf", BASE / "releases/20261110-ports/deployment/nginx.conf")
subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-t"], check=True)
subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-s", "reload"], check=True)

for name in ["control-current.sh", "current-runtime.json", "formal50-candidate.json"]:
    shutil.copyfile(release / ("previous-" + name), BASE / "deployment" / name)

subprocess.run(["docker", "update", "--restart=no", record["container"]], check=True)
subprocess.run(["docker", "stop", "-t", "45", record["container"]], check=True)
print("PREVIOUS_FORMAL50_RELEASE_RESTORED", record["previous_container"])
