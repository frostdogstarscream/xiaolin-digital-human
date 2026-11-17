"""Atomically cut over https://36.133.88.94:6444/ (xiaolin-nginx-1) onto validated
xiaolin-formal50-dit-v2-fay, expose passwordless Fay Persona & MCP reverse-proxy routes
with HTTPS/WSS same-origin shim injection, retire obsolete pants container, and keep 1-command rollback.
"""
import json
import re
import subprocess
import urllib.request
from pathlib import Path

BASE = Path("/opt/xiaolin")
record = json.loads((BASE / "deployment/dit-v2-fay-release.json").read_text(encoding="utf-8"))
release = Path(record["release"])
port = record["port"]

validation = json.loads((release / "validation-dit-v2-fay.json").read_text(encoding="utf-8"))
assert validation["status"] == "PASSED", validation

url_base = f"http://127.0.0.1:{port}"
with urllib.request.urlopen(url_base + "/api/health", timeout=5) as response:
    health = json.load(response)
assert health["status"] == "ready" and health["material_version"] == "rife-dit-v2", health

nginx = BASE / "releases/20261110-ports/deployment/nginx.conf"
old_nginx_src = nginx.read_text(encoding="utf-8")

m_server = re.search(r"server_name\s+([^;]+);", old_nginx_src)
server_name = m_server.group(1).strip() if m_server else "36.133.88.94"

new_nginx_src = f"""events {{}}
http {{
  map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
  server {{
    listen 6444 ssl;
    server_name {server_name};
    ssl_certificate /certs/server.crt;
    ssl_certificate_key /certs/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 5m;

    # Passwordless Fay native Message/Persona UI (:5000) with HTTPS/WSS shim injection
    location = /fay {{
      return 302 /fay/;
    }}
    location /fay/ {{
      proxy_pass http://127.0.0.1:5000/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Accept-Encoding "";
      sub_filter '<head>' '<head><script src="/fay-https-shim.js"></script>';
      sub_filter_once on;
    }}
    location = /setting {{
      proxy_pass http://127.0.0.1:5000/setting;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Accept-Encoding "";
      sub_filter '<head>' '<head><script src="/fay-https-shim.js"></script>';
      sub_filter_once on;
    }}

    # Passwordless Fay native MCP Console (:5010)
    location = /Page3 {{
      proxy_pass http://127.0.0.1:5010/Page3;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Accept-Encoding "";
      sub_filter '<head>' '<head><script src="/fay-https-shim.js"></script>';
      sub_filter_once on;
    }}
    location ^~ /api/mcp/ {{
      proxy_pass http://127.0.0.1:5010/api/mcp/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_read_timeout 120s;
    }}

    # Fay web status WebSocket (:10003) over WSS
    location = /fay-ws {{
      proxy_pass http://127.0.0.1:10003;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
    }}

    # Fay native :5000 APIs & assets
    location ~ ^/api/(submit|get-data|start-live|stop-live|send|get-msg|get-msg-by-id|get-member-list|add-user|get-run-status|delete-user|get-user-extra-info|update-user-extra-info|get-user-portrait|update-user-portrait|get-system-status|get-audio-config|adopt-msg|unadopt-msg|clear-memory|start-genagents|local-image|open-image|execution-status|execution-cancel|execution-modify|get-voice-list|get-audio-device-list)(/|$) {{
      proxy_pass http://127.0.0.1:5000;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_read_timeout 120s;
    }}
    location ^~ /v1/ {{
      proxy_pass http://127.0.0.1:5000/v1/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_buffering off;
      proxy_read_timeout 300s;
    }}
    location ^~ /audio/ {{
      proxy_pass http://127.0.0.1:5000/audio/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
    }}
    location ^~ /robot/ {{
      proxy_pass http://127.0.0.1:5000/robot/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
    }}
    location ~ ^/(to-greet|to-wake|to-stop-talking|transparent-pass)$ {{
      proxy_pass http://127.0.0.1:5000;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
    }}

    # Unified Fay + FayMCP static assets (:5000 primary, 404 fallback to :5010)
    location ^~ /static/ {{
      proxy_pass http://127.0.0.1:5000/static/;
      proxy_set_header Host $http_host;
      proxy_intercept_errors on;
      error_page 404 = @faymcp_static;
    }}
    location @faymcp_static {{
      proxy_pass http://127.0.0.1:5010;
      proxy_set_header Host $http_host;
    }}

    # Retained manual 50fps preview endpoint
    location ^~ /experiments/50fps/ {{
      proxy_pass http://127.0.0.1:8788/;
      proxy_set_header Host $http_host;
      proxy_set_header Origin $http_origin;
      proxy_set_header X-Xiaolin-User preview;
      proxy_read_timeout 3600s;
      proxy_buffering off;
    }}

    # Formal Skirt Xiaolin 50fps Dual-Engine Studio
    location / {{
      proxy_pass http://127.0.0.1:{port};
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Origin $http_origin;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      proxy_buffering off;
    }}
  }}
}}
"""
nginx.write_text(new_nginx_src, encoding="utf-8")

try:
    subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-t"], check=True)
    subprocess.run(["docker", "update", "--restart=unless-stopped", record["container"]], check=True)
    subprocess.run(["docker", "exec", "xiaolin-nginx-1", "nginx", "-s", "reload"], check=True)
except Exception:
    nginx.write_text(old_nginx_src, encoding="utf-8")
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

# Clean up obsolete stopped pants presenter container if present and stopped.
try:
    p_running = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.Running}}", "xiaolin-presenter-1"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if p_running == "false":
        subprocess.run(["docker", "rm", "xiaolin-presenter-1"], check=True)
except Exception:
    pass

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
    lipsync_model="xiaolin-dit-v2-256gan",
    material_version="rife-dit-v2",
    dual_dialogue_modes=True,
    fay_proxy_enabled=True,
    legacy_fay_speech_stopped=False,
)
runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")

candidate = dict(
    release=record["release"],
    container=record["container"],
    candidate_port=port,
    fps=50,
    lipsync_backend="wav2lip",
    lipsync_model="xiaolin-dit-v2-256gan",
    precision="fp16",
    baseline=record["baseline"],
    material_version="rife-dit-v2",
    dual_dialogue_modes=True,
    fay_proxy_enabled=True,
)
(BASE / "deployment/formal50-candidate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
(release / "activated.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
print("FORMAL_6444_DIT_V2_FAY_ACTIVATED", json.dumps(candidate, ensure_ascii=False))
