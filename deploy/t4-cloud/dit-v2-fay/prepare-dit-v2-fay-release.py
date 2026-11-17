"""Stage the blue-green formal50-dit-v2-fay release alongside the active formal container on Tesla T4.

Reuses the existing 33 GiB rife-dit-v2 material-cache and DiT-v2 weights via symlinks,
deploys the A/B dual-engine (Qwen Realtime + Fay persona/MCP <-> Fay brain),
the passwordless Fay proxy helpers, and the 1080x1920 portrait Studio UI with live subtitles.
"""
import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path("/opt/xiaolin")
STAGING = Path(__file__).resolve().parent
PAYLOAD = STAGING / "payload"

runtime_current = json.loads((BASE / "deployment/current-runtime.json").read_text(encoding="utf-8"))
cand_current = json.loads((BASE / "deployment/formal50-candidate.json").read_text(encoding="utf-8"))
source_release = Path(runtime_current.get("formal_release") or cand_current["release"])
previous_container = runtime_current.get("formal_container") or cand_current["container"]

nginx_path = BASE / "releases/20261110-ports/deployment/nginx.conf"
nginx_src = nginx_path.read_text(encoding="utf-8")
m_port = re.search(r"proxy_pass\s+http://127\.0\.0\.1:(877\d);", nginx_src)
assert m_port, "Could not parse current formal upstream port (877x) from nginx.conf"
previous_port = int(m_port.group(1))
candidate_port = 8776 if previous_port != 8776 else 8775

ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
release = BASE / "releases" / f"formal50-dit-v2-fay-{ts}"
root = release / "avatar-2d"
root.mkdir(parents=True)

for name in ["qwen-realtime-v2", "presenter-v2-1080", "presenter-50fps"]:
    shutil.copytree(
        source_release / "avatar-2d/experiments" / name,
        root / "experiments" / name,
        ignore=shutil.ignore_patterns("__pycache__", "*.before-*"),
    )

qwen_dir = root / "experiments/qwen-realtime-v2"
for fname in [
    "fay_bridge.py",
    "capabilities.py",
    "gateway.py",
    "index.html",
    "demo.js",
    "fay-https-shim.js",
]:
    src = PAYLOAD / fname
    assert src.is_file(), f"Missing payload file: {src}"
    shutil.copy2(src, qwen_dir / fname)

for name in ["assets", "runtime", "models", "tools", "outputs"]:
    (root / name).symlink_to("/eval/avatar-2d/" + name, target_is_directory=True)
(root / "service").symlink_to("/app/avatar-2d/service", target_is_directory=True)
shutil.copy2(source_release / "avatar-2d/source-manifest.json", root / "source-manifest.json")

# Zero-copy reuse of the active 33 GiB rife-dit-v2 cache via same-filesystem hardlinks,
# keeping paths real inside the /formal Docker bind mount without cross-mount symlink issues.
def _link_or_copy(src_file, dst_file):
    import os
    try:
        os.link(src_file, dst_file)
    except OSError:
        shutil.copy2(src_file, dst_file)

shutil.copytree((source_release / "material-cache").resolve(), release / "material-cache", copy_function=_link_or_copy)
shutil.copytree((source_release / "dit-v2-assets").resolve(), release / "dit-v2-assets", ignore=shutil.ignore_patterns("__pycache__"))

# Stage state/ with mcp_enabled=True and dialogue_mode='qwen_realtime' ready.
(release / "state").mkdir(mode=0o700)
prev_settings = json.loads((source_release / "state/settings.json").read_text(encoding="utf-8"))
prev_settings["lipsync_backend"] = "wav2lip"
prev_settings.setdefault("dialogue_mode", "qwen_realtime")
prev_settings["mcp_enabled"] = True
prev_settings["revision"] = int(prev_settings.get("revision", 1)) + 1
(release / "state/settings.json").write_text(json.dumps(prev_settings, indent=2), encoding="utf-8")
(release / "state/capabilities.sqlite3").symlink_to("/eval/avatar-2d/runtime/qwen-realtime-v2/capabilities.sqlite3")

# Generate gateway50.py from the updated dual-engine gateway.py.
gw_src = (qwen_dir / "gateway.py").read_text(encoding="utf-8")
gw_src = gw_src.replace(
    "sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))",
    "sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))\nsys.path.insert(0,str(HERE.parent/'presenter-50fps'))",
    1,
)
gw_src = gw_src.replace(
    "self.assets=await asyncio.to_thread(self.engine.Assets)",
    "self.assets=await asyncio.to_thread(self.engine.Assets);self.configure_video(self.settings.value['lipsync_backend'])",
    1,
)
gw_src = gw_src.replace(
    "return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'live_engine_v2')",
    "return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'engine50')",
    1,
)
marker = "    async def settings_api(self,request):"
assert marker in gw_src, "settings_api marker missing"
gw_src = gw_src.replace(
    marker,
    """    @staticmethod
    def configure_video(backend):
        from server import webrtc
        if backend=='wav2lip':
            from encoder50 import configure
            webrtc.VIDEO_PTIME=.02
        else:
            from video_encoder import configure
            webrtc.VIDEO_PTIME=.04
        configure()
"""
    + marker,
    1,
)
gw_src = gw_src.replace(
    "self.engine=next_engine;self.assets=next_assets",
    "self.engine=next_engine;self.assets=next_assets\n                if changed:self.configure_video(data['lipsync_backend'])",
    1,
)
gw_src = gw_src.replace(
    "profile='presenter-v2-1080',",
    "profile='presenter-formal-50fps',video_fps=50 if self.settings.value['lipsync_backend']=='wav2lip' else 25,"
    "material_version=getattr(self.assets,'transition_plan',None).get('version') if getattr(self.assets,'transition_plan',None) else None,",
    1,
)
gw_src = gw_src.replace(
    "lipsync_decoder='original',",
    "lipsync_decoder='original',lipsync_model='xiaolin-dit-v2-256gan' if self.settings.value['lipsync_backend']=='wav2lip' else 'musetalk-1.5',",
    1,
)
for needle in ("'engine50'", "configure_video", "xiaolin-dit-v2-256gan", "material_version"):
    assert needle in gw_src, f"gateway50.py generation missing {needle}"

gw50_path = qwen_dir / "gateway50.py"
gw50_path.write_text(gw_src, encoding="utf-8")

for check_file in (qwen_dir / "fay_bridge.py", qwen_dir / "capabilities.py", gw50_path):
    compile(check_file.read_text(encoding="utf-8"), str(check_file), "exec")

shutil.copy2(STAGING / "validate-dit-v2-fay-release.py", release / "validate-dit-v2-fay-release.py")

shutil.copy2(nginx_path, release / "previous-nginx.conf")
for name in ["control-current.sh", "current-runtime.json", "formal50-candidate.json"]:
    shutil.copy2(BASE / "deployment" / name, release / ("previous-" + name))

info = json.loads(subprocess.check_output(["docker", "inspect", previous_container], text=True))[0]
(release / "previous-container.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
(release / "previous-container.json").chmod(0o600)

# Retire stale 8766 realtime-ingress.json so Fay core TTS cleanly emits WAV files via WS 10002 & /audio/
stale_ingress = BASE / "shared/data/presenter-runtime/realtime-ingress.json"
if stale_ingress.exists():
    stale_ingress.replace(BASE / "shared/data/presenter-runtime/realtime-ingress.json.legacy-8766")

record = dict(
    release=str(release),
    previous_release=str(source_release),
    previous_container=previous_container,
    previous_port=previous_port,
    container="xiaolin-formal50-dit-v2-fay",
    port=candidate_port,
    formal_gpu=runtime_current.get("formal_gpu") or "GPU-d83c041f-3543-6c67-faf0-23f3d1910f44",
    baseline=cand_current.get("baseline", runtime_current.get("baseline25", "")),
    material_version="rife-dit-v2",
    lipsync_model="xiaolin-dit-v2-256gan",
)
(BASE / "deployment/dit-v2-fay-release.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
