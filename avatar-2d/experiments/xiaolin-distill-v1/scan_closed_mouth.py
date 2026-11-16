"""Scan presenter-v2-1080 clips to find clean closed-mouth (non-teeth-baring) segments."""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Code\3D数字人\avatar-2d\tools")
from windows_runtime import prepare_runtime
prepare_runtime()

import cv2
import numpy as np

ROOT = Path(r"D:\Code\3D数字人\avatar-2d")
OUT = ROOT / "outputs" / "xiaolin-distill-v1"
OUT.mkdir(parents=True, exist_ok=True)

CLIPS = {
    "idle": ROOT / "assets/presenter-v2-1080/prepared/idle.mp4",
    "welcome-wave": ROOT / "assets/presenter-v2-1080/color-matched-20261111/welcome-wave.mp4",
    "goodbye-wave": ROOT / "assets/presenter-v2-1080/color-matched-20261111/goodbye-wave.mp4",
    "explain-open-palms": ROOT / "assets/presenter-v2-1080/color-matched-20261111/explain-open-palms.mp4",
    "acknowledge-nod": ROOT / "assets/presenter-v2-1080/color-matched-20261111/acknowledge-nod.mp4",
}

summary = {}
for name, video_path in CLIPS.items():
    coords_path = ROOT / f"runtime/presenter-v2-1080/avatars/{name}/coords.json"
    coords = json.loads(coords_path.read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(video_path))
    teeth_scores = []
    eye_scores = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok or idx >= len(coords):
            break
        y1, y2, x1, x2 = coords[idx]
        face = frame[y1:y2, x1:x2]
        h, w = face.shape[:2]
        # Mouth interior region: vertically ~66%..82% of S3FD face box, horizontally ~32%..68%
        mouth_roi = face[int(h * 0.66):int(h * 0.82), int(w * 0.32):int(w * 0.68)]
        hsv = cv2.cvtColor(mouth_roi, cv2.COLOR_BGR2HSV)
        # Teeth are bright (high V) and low saturation (low S, unlike pink/red lips)
        bright_low_sat = ((hsv[:, :, 2] > 155) & (hsv[:, :, 1] < 65)).mean()
        teeth_scores.append(float(bright_low_sat))
        # Eye openness proxy: dark iris/pupil contrast in upper-mid face (~34%..48% height)
        eye_roi = cv2.cvtColor(face[int(h * 0.34):int(h * 0.48), int(w * 0.18):int(w * 0.82)], cv2.COLOR_BGR2GRAY)
        eye_dark = float((eye_roi < 65).mean())
        eye_scores.append(eye_dark)
        idx += 1
    cap.release()

    arr = np.array(teeth_scores)
    closed_mask = arr < 0.015
    # Find contiguous closed runs
    runs = []
    start = None
    for i, val in enumerate(closed_mask):
        if val and start is None:
            start = i
        elif not val and start is not None:
            if i - start >= 5:
                runs.append({"start": start, "end": i - 1, "frames": i - start, "seconds": round((i - start) / 25.0, 2),
                             "mean_teeth": round(float(arr[start:i].mean()), 5)})
            start = None
    if start is not None and len(closed_mask) - start >= 5:
        runs.append({"start": start, "end": len(closed_mask) - 1, "frames": len(closed_mask) - start,
                     "seconds": round((len(closed_mask) - start) / 25.0, 2),
                     "mean_teeth": round(float(arr[start:].mean()), 5)})

    summary[name] = {
        "total_frames": idx,
        "min_teeth": round(float(arr.min()), 5),
        "p10_teeth": round(float(np.percentile(arr, 10)), 5),
        "median_teeth": round(float(np.median(arr)), 5),
        "max_teeth": round(float(arr.max()), 5),
        "closed_runs": runs,
    }
    print(f"[{name}] total={idx} min={arr.min():.4f} p10={np.percentile(arr,10):.4f} med={np.median(arr):.4f} max={arr.max():.4f} runs={runs}")

(OUT / "closed-mouth-scan.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
