"""Check 4090 Python environment packages and inspect exact file list/sizes on hf-mirror for Sonic."""
import importlib.util
import json
import sys
import urllib.request

pkgs = [
    "torch", "torchaudio", "torchvision", "diffusers", "transformers",
    "omegaconf", "einops", "librosa", "imageio", "imageio_ffmpeg",
    "huggingface_hub", "mediapipe", "cv2", "PIL", "accelerate", "safetensors"
]
status = {}
for p in pkgs:
    spec = importlib.util.find_spec(p)
    if spec is not None:
        try:
            m = __import__(p)
            status[p] = getattr(m, "__version__", "installed")
        except Exception as e:
            status[p] = f"err: {e}"
    else:
        status[p] = None

print("PKG_STATUS:", json.dumps(status, indent=2))

for repo in ["LeonJoe13/Sonic", "stabilityai/stable-video-diffusion-img2vid-xt"]:
    url = f"https://hf-mirror.com/api/models/{repo}/tree/main?recursive=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            items = json.loads(resp.read().decode("utf-8"))
        files = [(it["path"], round(it.get("size", 0) / (1024**2), 1)) for it in items if it.get("type") == "file"]
        print(f"REPO {repo}:")
        for path, mb in files:
            print(f"  {path}: {mb} MB")
    except Exception as e:
        print(f"REPO {repo} ERR: {e}")
