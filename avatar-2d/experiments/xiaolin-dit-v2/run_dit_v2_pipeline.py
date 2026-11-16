"""End-to-end resilient orchestrator on RTX 4090 (F:/xiaolin/dit-distill-v2):
1. Preserves all previously downloaded bytes of Sonic/unet.pth (part1 + upper_part = ~3,045 MB)
   and downloads ONLY the remaining byte gaps using 6 concurrent curl Range workers over the
   active internet route (no hardcoded stale NIC IP!), cutting remaining download time to a few minutes.
2. Verifies exact byte length and PyTorch state_dict integrity via torch.load(..., weights_only=True).
3. Sequentially runs Step 0 -> Step 1 (Sonic 512x512 DiT Teacher) -> Step 2 (Skull-Locked 256x256
   Multi-Pose Dataset) -> Step 3 (256x256 Dual-Ref PatchGAN Student + 50fps 16s 3-Way Preview).
"""
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"F:\xiaolin\dit-distill-v2")
CKPT_SONIC = ROOT / "vendor" / "Sonic" / "checkpoints" / "Sonic"
UNET_DST = CKPT_SONIC / "unet.pth"
PART1 = CKPT_SONIC / "unet.pth.part"
PART2 = CKPT_SONIC / "unet.pth.upper_part"
SPLIT_META = CKPT_SONIC / "unet_split.txt"
MS_UNET_URL = "https://www.modelscope.cn/models/ApacheOne/ComfyUI-Sonic-models/resolve/master/sonic/unet.pth"


def resolve_cdn_and_size(url: str) -> tuple[str, int]:
    """Resolves signed CDN URL and exact file byte length, and detects fastest outbound interface."""
    # Check if 192.168.* WLAN IP is active; curl without --interface may pick lower-metric 10.36.154.54!
    wlan_cands = []
    out_ip = subprocess.check_output(["ipconfig"], text=True, errors="replace")
    for ln in out_ip.splitlines():
        if "192.168." in ln and ":" in ln and ("IPv4" in ln or "Address" in ln or "192.168." in ln.split(":")[-1]):
            cand = ln.split(":")[-1].strip()
            if cand.startswith("192.168.") and not cand.endswith(".1") and cand not in wlan_cands:
                wlan_cands.append(cand)

    # Test curl header fetch via candidate 192.168.* WLAN IPs first, then default route
    for iface in wlan_cands + [None]:
        cmd = ["curl.exe"]
        if iface:
            cmd += ["--interface", iface]
        cmd += ["-L", "--fail", "-s", "-S", "--connect-timeout", "10", "-r", "0-0", "-D", "-", "-o", "NUL", url]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            tot = 0
            for hline in proc.stdout.splitlines():
                if hline.lower().startswith("content-range:") and "/" in hline:
                    tot = int(hline.split("/")[-1].strip())
            if tot > 6_000_000_000:
                print(f"[Orchestrator] Active internet route verified (iface={iface or 'default'}, size={tot} bytes).", flush=True)
                return iface, tot
    raise RuntimeError("Could not reach ModelScope CDN on any interface!")


def split_into_subranges(start_b: int, end_b: int, n_splits: int) -> list[tuple[int, int]]:
    if start_b > end_b:
        return []
    length = end_b - start_b + 1
    step = max(16 * 1024 * 1024, (length + n_splits - 1) // n_splits)
    out = []
    cur = start_b
    while cur <= end_b:
        hi = min(end_b, cur + step - 1)
        out.append((cur, hi))
        cur = hi + 1
    return out


def spawn_chunk_curl(iface: str | None, start_b: int, end_b: int, dest_part: Path) -> subprocess.Popen | None:
    got = dest_part.stat().st_size if dest_part.exists() else 0
    need = end_b - start_b + 1
    if got >= need:
        return None
    app = Path(str(dest_part) + ".app")
    app.unlink(missing_ok=True)
    cmd = ["curl.exe"]
    if iface:
        cmd += ["--interface", iface]
    cmd += [
        "-L", "--fail", "-s", "-S",
        "--connect-timeout", "15",
        "--speed-time", "30", "--speed-limit", "20480",
        "-r", f"{start_b + got}-{end_b}",
        "-o", str(app),
        MS_UNET_URL,
    ]
    return subprocess.Popen(cmd)


def flush_app(dest_part: Path, max_len: int):
    app = Path(str(dest_part) + ".app")
    if app.exists():
        if app.stat().st_size > 0:
            dest_part.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_part, "ab") as df, open(app, "rb") as sf:
                shutil.copyfileobj(sf, df, length=32 * 1024 * 1024)
        app.unlink(missing_ok=True)
    if dest_part.exists() and dest_part.stat().st_size > max_len:
        with open(dest_part, "r+b") as fh:
            fh.truncate(max_len)


def ensure_sonic_unet():
    CKPT_SONIC.mkdir(parents=True, exist_ok=True)
    subprocess.call(["taskkill", "/IM", "curl.exe", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    iface, total_bytes = resolve_cdn_and_size(MS_UNET_URL)
    if UNET_DST.exists() and UNET_DST.stat().st_size == total_bytes:
        print(f"[Orchestrator] Sonic/unet.pth already complete ({total_bytes / 1024**2:.2f} MB).", flush=True)
        return

    p1_size = PART1.stat().st_size if PART1.exists() else 0
    p2_size = PART2.stat().st_size if PART2.exists() else 0
    split_byte = int(SPLIT_META.read_text().strip()) if SPLIT_META.exists() else p1_size

    # Validate existing segments:
    # Segment A (already on disk): [0 .. p1_size - 1] in PART1
    # Gap 1 (to download):         [p1_size .. split_byte - 1] -> split into 5 parallel chunks!
    # Segment B (already on disk): [split_byte .. split_byte + p2_size - 1] in PART2
    # Gap 2 (to download):         [split_byte + p2_size .. total_bytes - 1] -> 1 parallel chunk!
    if p1_size > split_byte:
        with open(PART1, "r+b") as f:
            f.truncate(split_byte)
        p1_size = split_byte
    if split_byte + p2_size > total_bytes:
        p2_size = max(0, total_bytes - split_byte)
        with open(PART2, "r+b") as f:
            f.truncate(p2_size)

    gap1_ranges = split_into_subranges(p1_size, split_byte - 1, 5)
    gap2_ranges = split_into_subranges(split_byte + p2_size, total_bytes - 1, 1)

    tasks = []
    for idx, (sb, eb) in enumerate(gap1_ranges):
        tasks.append(("gap1", idx, sb, eb, CKPT_SONIC / f"unet.gap1_{idx}.bin"))
    for idx, (sb, eb) in enumerate(gap2_ranges):
        tasks.append(("gap2", idx, sb, eb, CKPT_SONIC / f"unet.gap2_{idx}.bin"))

    for _, _, sb, eb, fp in tasks:
        flush_app(fp, eb - sb + 1)

    preserved_bytes = p1_size + p2_size
    print(
        f"[Orchestrator] Resuming Sonic/unet.pth: preserved={preserved_bytes/1024**2:.1f} MB, "
        f"remaining={(total_bytes - preserved_bytes)/1024**2:.1f} MB across {len(tasks)} parallel WLAN streams...",
        flush=True,
    )

    procs = {}
    for k, (_, _, sb, eb, fp) in enumerate(tasks):
        pr = spawn_chunk_curl(iface, sb, eb, fp)
        if pr is not None:
            procs[k] = pr
        time.sleep(0.25)

    last_done = preserved_bytes + sum(fp.stat().st_size for _, _, _, _, fp in tasks if fp.exists())
    last_t = time.perf_counter()

    while procs:
        time.sleep(15.0)
        # Re-detect WLAN IP if all streams stall
        for k in list(procs.keys()):
            pr = procs[k]
            _, _, sb, eb, fp = tasks[k]
            need = eb - sb + 1
            if pr.poll() is not None:
                flush_app(fp, need)
                got = fp.stat().st_size if fp.exists() else 0
                if got >= need:
                    print(f"  [Stream #{k}] COMPLETE ({need/1024**2:.1f} MB)", flush=True)
                    del procs[k]
                else:
                    try:
                        iface, _ = resolve_cdn_and_size(MS_UNET_URL)
                    except Exception:
                        pass
                    procs[k] = spawn_chunk_curl(iface, sb, eb, fp)

        cur_gaps = 0
        for _, _, sb, eb, fp in tasks:
            app = Path(str(fp) + ".app")
            cur_gaps += (fp.stat().st_size if fp.exists() else 0) + (app.stat().st_size if app.exists() else 0)
        cur_tot = min(total_bytes, preserved_bytes + cur_gaps)
        now = time.perf_counter()
        rate = (cur_tot - last_done) / max(1e-3, (now - last_t)) / (1024 ** 2)
        rem_mb = max(0.0, (total_bytes - cur_tot) / (1024 ** 2))
        eta_min = rem_mb / max(0.05, rate) / 60.0
        last_done, last_t = cur_tot, now
        print(
            f"  [DL] {cur_tot/1024**2:.1f}/{total_bytes/1024**2:.1f} MB ({100.0*cur_tot/total_bytes:.1f}%) | "
            f"active_streams={len(procs)} | speed={rate:.2f} MB/s | ETA={eta_min:.1f} min",
            flush=True,
        )

    # Assemble in exact byte order onto PART1 -> UNET_DST!
    print("[Orchestrator] All gap streams complete! Assembling Sonic/unet.pth in exact byte order...", flush=True)
    ordered_pieces = []
    for grp, _, sb, eb, fp in [t for t in tasks if t[0] == "gap1"]:
        assert fp.stat().st_size == (eb - sb + 1), (fp, fp.stat().st_size, eb - sb + 1)
        ordered_pieces.append((fp, True))
    if p2_size > 0:
        ordered_pieces.append((PART2, True))
    for grp, _, sb, eb, fp in [t for t in tasks if t[0] == "gap2"]:
        assert fp.stat().st_size == (eb - sb + 1), (fp, fp.stat().st_size, eb - sb + 1)
        ordered_pieces.append((fp, True))

    PART1.parent.mkdir(parents=True, exist_ok=True)
    with open(PART1, "ab") as dst_f:
        for src_p, _ in ordered_pieces:
            with open(src_p, "rb") as sf:
                shutil.copyfileobj(sf, dst_f, length=64 * 1024 * 1024)

    assert PART1.stat().st_size == total_bytes, f"Size mismatch: {PART1.stat().st_size} != {total_bytes}"
    if UNET_DST.exists():
        UNET_DST.unlink()
    PART1.rename(UNET_DST)

    print("[Orchestrator] Verifying Sonic/unet.pth PyTorch state_dict integrity...", flush=True)
    import torch
    sd = torch.load(str(UNET_DST), map_location="cpu", weights_only=True)
    print(f"  -> Integrity 100% VERIFIED ({len(sd)} tensors loaded cleanly)!", flush=True)
    del sd

    # Clean up temporary gap parts only AFTER torch.load verification passes!
    for src_p, del_ok in ordered_pieces:
        if del_ok:
            src_p.unlink(missing_ok=True)
    SPLIT_META.unlink(missing_ok=True)


def run_step(script_name: str):
    print(f"\n==================== RUNNING {script_name} ====================", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.call([sys.executable, "-u", str(ROOT / script_name)])
    if rc != 0:
        raise RuntimeError(f"{script_name} failed with exit code {rc}")
    print(f"==================== FINISHED {script_name} in {time.perf_counter() - t0:.1f}s ====================\n", flush=True)


if __name__ == "__main__":
    t_all = time.perf_counter()
    ensure_sonic_unet()
    run_step("step0_setup_and_download.py")
    run_step("step1_build_hd_refs_and_sonic_teacher.py")
    run_step("step2_align_and_build_dataset256.py")
    run_step("step3_train_gan256_and_preview15s.py")
    print(f"ALL_DIT_V2_PIPELINE_STEPS_COMPLETE in {(time.perf_counter() - t_all)/60.0:.2f} min!", flush=True)
