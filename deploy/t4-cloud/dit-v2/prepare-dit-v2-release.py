"""Stage the blue-green formal50-dit-v2 release alongside the active formal container on Tesla T4."""
import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path("/opt/xiaolin")
STAGING = Path(__file__).resolve().parent

runtime_current = json.loads((BASE / "deployment/current-runtime.json").read_text(encoding="utf-8"))
cand_current = json.loads((BASE / "deployment/formal50-candidate.json").read_text(encoding="utf-8"))
source_release = Path(runtime_current.get("formal_release") or cand_current["release"])
previous_container = runtime_current.get("formal_container") or cand_current["container"]

nginx_path = BASE / "releases/20261110-ports/deployment/nginx.conf"
nginx_src = nginx_path.read_text(encoding="utf-8")
m_port = re.search(r"proxy_pass\s+http://127\.0\.0\.1:(\d+);", nginx_src)
assert m_port, "Could not parse current upstream port from nginx.conf"
previous_port = int(m_port.group(1))
candidate_port = 8775 if previous_port != 8775 else 8776

ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
release = BASE / "releases" / f"formal50-dit-v2-{ts}"
root = release / "avatar-2d"
root.mkdir(parents=True)

for name in ["qwen-realtime-v2", "presenter-v2-1080", "presenter-50fps"]:
    shutil.copytree(
        source_release / "avatar-2d/experiments" / name,
        root / "experiments" / name,
        ignore=shutil.ignore_patterns("__pycache__", "*.before-*"),
    )

for name in ["assets", "runtime", "models", "tools", "outputs"]:
    (root / name).symlink_to("/eval/avatar-2d/" + name, target_is_directory=True)
(root / "service").symlink_to("/app/avatar-2d/service", target_is_directory=True)
shutil.copy2(source_release / "avatar-2d/source-manifest.json", root / "source-manifest.json")

(release / "state").mkdir(mode=0o700)
shutil.copy2(source_release / "state/settings.json", release / "state/settings.json")
(release / "state/capabilities.sqlite3").symlink_to("/eval/avatar-2d/runtime/qwen-realtime-v2/capabilities.sqlite3")

d_dir = release / "dit-v2-assets"
d_dir.mkdir(parents=True, exist_ok=True)
for fname in [
    "xiaolin_dit_student256_full_best.pth",
    "rife_flownet.pkl",
    "xiaolin_student256_gan.py",
    "material-input.json",
    "build-rife-dit-v2-cache.py",
    "validate-dit-v2-release.py",
]:
    shutil.copy2(STAGING / fname, d_dir / fname)

exp50 = root / "experiments/presenter-50fps"
shutil.copy2(exp50 / "engine50.py", exp50 / "engine50.py.before-dit-v2")
shutil.copy2(exp50 / "render50.py", exp50 / "render50.py.before-dit-v2")
shutil.copy2(STAGING / "engine50_dit_v2.py", exp50 / "engine50.py")
shutil.copy2(STAGING / "render50_dit_v2.py", exp50 / "render50.py")

sched_path = exp50 / "idle_scheduler.py"
sched_src = sched_path.read_text(encoding="utf-8")
if "def seek(" not in sched_src:
    sched_src += """
    def seek(self, index):
        for current, segment in enumerate(self.segments):
            if segment['start'] <= index < segment['end']:
                self.current = current
                self.index = index
                return
        raise ValueError('Idle entry outside the available segments')
"""
    compile(sched_src, str(sched_path), "exec")
    sched_path.write_text(sched_src, encoding="utf-8")

gw_path = root / "experiments/qwen-realtime-v2/gateway50.py"
gw_src = gw_path.read_text(encoding="utf-8")
if "material_version=" not in gw_src:
    gw_src = gw_src.replace(
        "profile='presenter-formal-50fps',",
        "profile='presenter-formal-50fps',material_version=getattr(self.assets,'transition_plan',None).get('version') if getattr(self.assets,'transition_plan',None) else None,",
    )
if "lipsync_model=" not in gw_src:
    gw_src = gw_src.replace(
        "lipsync_decoder='original',",
        "lipsync_decoder='original',lipsync_model='xiaolin-dit-v2-256gan' if self.settings.value['lipsync_backend']=='wav2lip' else 'musetalk-1.5',",
    )
else:
    gw_src = gw_src.replace("xiaolin-ultralight-v1", "xiaolin-dit-v2-256gan")
compile(gw_src, str(gw_path), "exec")
gw_path.write_text(gw_src, encoding="utf-8")

for check_file in [exp50 / "engine50.py", exp50 / "render50.py", d_dir / "xiaolin_student256_gan.py", d_dir / "build-rife-dit-v2-cache.py"]:
    compile(check_file.read_text(encoding="utf-8"), str(check_file), "exec")

shutil.copy2(nginx_path, release / "previous-nginx.conf")
for name in ["control-current.sh", "current-runtime.json", "formal50-candidate.json"]:
    shutil.copy2(BASE / "deployment" / name, release / ("previous-" + name))

info = json.loads(subprocess.check_output(["docker", "inspect", previous_container], text=True))[0]
(release / "previous-container.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
(release / "previous-container.json").chmod(0o600)

record = dict(
    release=str(release),
    previous_release=str(source_release),
    previous_container=previous_container,
    previous_port=previous_port,
    container="xiaolin-formal50-dit-v2",
    port=candidate_port,
    build_gpu="GPU-ef5cc59f-01e3-6165-147c-15bcbb737d0f",
    formal_gpu="GPU-d83c041f-3543-6c67-faf0-23f3d1910f44",
    baseline=cand_current.get("baseline", runtime_current.get("baseline25", "")),
    material_version="rife-dit-v2",
    lipsync_model="xiaolin-dit-v2-256gan",
)
(BASE / "deployment/dit-v2-release.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
