import os
import subprocess
import urllib.request
from pathlib import Path

root = Path(r"F:\xiaolin\dit-distill-v2")
print("=== 1. DIT-DISTILL-V2 FILE TREE & SIZES ===")
for sub in ["vendor/Sonic/checkpoints", "teacher", "dataset256", "checkpoints", "outputs"]:
    d = root / sub
    print(f"\n[{sub}] exists={d.exists()}")
    if d.exists():
        for p in sorted(d.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(d))
                if ".cache" in rel:
                    continue
                print(f"  {rel:60s} {p.stat().st_size / 1024**2:9.2f} MB")

print("\n=== 2. GPU STATUS ===")
out_gpu = subprocess.check_output(
    ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader"],
    text=True,
)
print(" ", out_gpu.strip())

print("\n=== 3. NETWORK & INTERNET CHECK (DEFAULT ROUTE) ===")
out_ip = subprocess.check_output(["ipconfig"], text=True, errors="replace")
for ln in out_ip.splitlines():
    if any(k in ln for k in ["IPv4", "WLAN", "Ethernet", "10.36", "192.168", "Default Gateway", "默认网关", "无线", "以太网"]):
        print(" ", ln)

try:
    req = urllib.request.Request(
        "https://www.modelscope.cn/models/ApacheOne/ComfyUI-Sonic-models/resolve/master/sonic/unet.pth",
        headers={"Range": "bytes=0-1048575", "User-Agent": "Mozilla/5.0"},
    )
    import time
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=12) as r:
        buf = r.read()
        cr = r.headers.get("Content-Range", "")
    dt = time.perf_counter() - t0
    print(f"\n[ModelScope Default Route OK] 1.00 MB in {dt:.2f}s ({1.0/dt:.2f} MB/s) | Content-Range={cr}")
except Exception as e:
    print(f"\n[ModelScope Default Route ERR] {e}")
