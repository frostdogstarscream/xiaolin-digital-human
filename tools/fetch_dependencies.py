"""Download pinned upstream Unity packages without running upstream install scripts."""
from __future__ import annotations
import hashlib
import io
import json
import tarfile
import time
import urllib.request
import urllib.parse
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "_downloads"
PROJECT = ROOT / "unity"
CACHE.mkdir(exist_ok=True)
LOCK = []


def fetch(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AvatarKioskDependencyFetcher/1.0"})
            with urllib.request.urlopen(req, timeout=90) as response:
                data = response.read()
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.write_bytes(data)
            temp.replace(destination)
            return destination
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def unitypackage(name, url):
    source = fetch(url, CACHE / name)
    data = source.read_bytes()
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = {m.name: m for m in archive.getmembers() if m.isfile()}
        for name_, member in members.items():
            if not name_.endswith("/pathname"):
                continue
            path = archive.extractfile(member).read().decode("utf-8").strip("\x00\r\n")
            parts = PurePosixPath(path).parts
            if not parts or parts[0] not in ("Assets", "Packages") or ".." in parts or ":" in path:
                raise ValueError("Unsafe package path")
            prefix = name_.rsplit("/", 1)[0]
            dest = PROJECT.joinpath(*parts)
            for suffix, target in [("asset", dest), ("asset.meta", Path(str(dest) + ".meta"))]:
                item = members.get(prefix + "/" + suffix)
                if item:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(item).read())
                    count += 1
    LOCK.append({"url": url, "sha256": hashlib.sha256(data).hexdigest(), "files": count})
    print(source.name, count, "files", flush=True)


def main():
    unitypackage("ChatdollKit_0.8.16.unitypackage", "https://github.com/uezo/ChatdollKit/releases/download/v0.8.16/ChatdollKit_0.8.16.unitypackage")
    unitypackage("ChatdollKit_VRMExtension_0.8.16.unitypackage", "https://github.com/uezo/ChatdollKit/releases/download/v0.8.16/ChatdollKit_VRMExtension_0.8.16.unitypackage")
    unitypackage("VRM-0.131.4.unitypackage", "https://github.com/vrm-c/UniVRM/releases/download/v0.131.4/VRM-0.131.4_efd2.unitypackage")
    unitypackage("UniVRM-0.131.4.unitypackage", "https://github.com/vrm-c/UniVRM/releases/download/v0.131.4/UniVRM-0.131.4_efd2.unitypackage")
    tree_path = fetch("https://api.github.com/repos/hecomi/uLipSync/git/trees/v3.1.4?recursive=1", CACHE / "ulipsync-tree.json")
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    files = [x["path"] for x in tree["tree"] if x["type"] == "blob" and
             x["path"].startswith("Assets/uLipSync/") and "/Samples" not in x["path"]]
    def copy(path):
        return fetch("https://raw.githubusercontent.com/hecomi/uLipSync/v3.1.4/" + urllib.parse.quote(path), PROJECT / path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(copy, files))
    LOCK.append({"repository": "https://github.com/hecomi/uLipSync", "tag": "v3.1.4", "tree": tree["sha"], "files": len(files)})
    for name, url in [
        ("ChatdollKit-LICENSE", "https://raw.githubusercontent.com/uezo/ChatdollKit/v0.8.16/LICENSE"),
        ("UniVRM-LICENSE", "https://raw.githubusercontent.com/vrm-c/UniVRM/v0.131.4/LICENSE.txt"),
        ("uLipSync-LICENSE", "https://raw.githubusercontent.com/hecomi/uLipSync/v3.1.4/LICENSE.md"),
    ]:
        fetch(url, ROOT / "licenses" / (name + ".txt"))
    (ROOT / "dependencies.lock.json").write_text(json.dumps(LOCK, indent=2), encoding="utf-8")
    print("Dependency sources ready.", flush=True)


if __name__ == "__main__":
    main()
