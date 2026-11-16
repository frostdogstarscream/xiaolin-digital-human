"""Registers scheduled task Xiaolin-DiTv2-50fps-4090 (InteractiveToken, port 18775)
without touching existing Xiaolin-MuseTalk-4090 (port 18774), starts it, and verifies
http://127.0.0.1:18775/api/health == ready.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

DIT_DIR = Path(r"F:\xiaolin\dit-distill-v2")
LOGS_DIR = DIT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
RUNNER_BAT = DIT_DIR / "live50" / "run-dit-v2-50fps.cmd"

RUNNER_BAT.write_text(
    '@echo off\r\n'
    '"F:\\xiaolin\\venv\\Scripts\\python.exe" -X utf8 "F:\\xiaolin\\dit-distill-v2\\live50\\start-xiaolin-4090-dit-v2.py" >> "F:\\xiaolin\\dit-distill-v2\\logs\\gateway50-dit-v2.log" 2>&1\r\n',
    encoding="utf-8",
)

# Inspect existing Xiaolin-MuseTalk-4090 XML template (read-only) so InteractiveToken & user match 100%
xml_out = subprocess.check_output(["schtasks", "/Query", "/TN", "Xiaolin-MuseTalk-4090", "/XML"], text=True, errors="replace")
# Replace command & arguments cleanly to point to RUNNER_BAT
import re
xml_new = re.sub(r"<Command>.*?</Command>", lambda _: f"<Command>{RUNNER_BAT}</Command>", xml_out, count=1, flags=re.DOTALL)
xml_new = re.sub(r"<Arguments>.*?</Arguments>", "", xml_new, count=1, flags=re.DOTALL)
xml_new = re.sub(r"<WorkingDirectory>.*?</WorkingDirectory>", lambda _: r"<WorkingDirectory>F:\xiaolin\app\avatar-2d</WorkingDirectory>", xml_new, count=1, flags=re.DOTALL)

xml_path = DIT_DIR / "live50" / "Xiaolin-DiTv2-50fps-4090.xml"
xml_path.write_bytes(xml_new.encode("utf-16"))

subprocess.run(["schtasks", "/End", "/TN", "Xiaolin-DiTv2-50fps-4090"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["schtasks", "/Create", "/TN", "Xiaolin-DiTv2-50fps-4090", "/XML", str(xml_path), "/F"], check=True)
subprocess.run(["schtasks", "/Run", "/TN", "Xiaolin-ASR-4090"], check=True)
subprocess.run(["schtasks", "/Run", "/TN", "Xiaolin-DiTv2-50fps-4090"], check=True)

url = "http://127.0.0.1:18775/api/health"
deadline = time.monotonic() + 90
while True:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            h = json.load(r)
            if h.get("status") == "ready":
                print("LIVE50_4090_HEALTH_READY", json.dumps({
                    "status": h.get("status"),
                    "lipsync_backend": h.get("lipsync_backend"),
                    "active_action": h.get("active_action"),
                    "automatic_gestures_enabled": h.get("automatic_gestures_enabled"),
                }, ensure_ascii=False), flush=True)
                break
    except Exception:
        if time.monotonic() >= deadline:
            log_tail = (LOGS_DIR / "gateway50-dit-v2.log").read_text(encoding="utf-8", errors="replace")[-2000:] if (LOGS_DIR / "gateway50-dit-v2.log").exists() else "no log"
            raise RuntimeError(f"Port 18775 health timeout:\n{log_tail}")
    time.sleep(1.5)

# Stop the background task after verification so GPU stays idle until user clicks Open-Xiaolin-4090-DiTv2.cmd!
subprocess.run(["schtasks", "/End", "/TN", "Xiaolin-DiTv2-50fps-4090"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("LIVE50_4090_VERIFIED_AND_PARKED_CLEANLY", flush=True)
