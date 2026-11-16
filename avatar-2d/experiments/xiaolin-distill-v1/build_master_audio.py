"""Build ~4.5-minute (272s = 6,800 frames @ 25fps) phonetically rich Mandarin training audio
and a separate ~22s unseen validation audio from cached Bailian speech samples (resampling 24k/44.1k -> 16k if needed, zero cloud cost).
"""
import hashlib
import json
import math
import random
import wave
from pathlib import Path
import numpy as np

WORKSPACE = Path(r"d:\Code\3D数字人")
SAMPLES_DIR = WORKSPACE / "fay-ue4/runtime/fay-local/app/samples"
OUT_DIR = WORKSPACE / "avatar-2d/outputs/xiaolin-distill-v1/dataset"


def resample_linear_16k(pcm: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return pcm
    n_out = int(round(len(pcm) * 16000.0 / sr))
    if n_out < 1600:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, pcm).astype(np.float32)


def read_any_wav_to_16k(path: Path):
    try:
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
    except Exception:
        return None
    if sw != 2 or sr not in (16000, 22050, 24000, 32000, 44100, 48000):
        return None
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    pcm = resample_linear_16k(pcm, sr)
    if len(pcm) < int(1.0 * 16000):
        return None
    rms = float(np.sqrt(np.mean(pcm ** 2)))
    peak = float(np.max(np.abs(pcm)))
    if rms < 0.015 or peak > 0.999:
        return None
    win = 320
    n_w = len(pcm) // win
    if n_w < 5:
        return None
    w_rms = np.array([np.sqrt(np.mean(pcm[i * win : (i + 1) * win] ** 2)) for i in range(n_w)])
    active = np.where(w_rms > 0.007)[0]
    if len(active) < 4:
        return None
    s0 = max(0, (int(active[0]) - 2) * win)
    s1 = min(len(pcm), (int(active[-1]) + 3) * win)
    trimmed = pcm[s0:s1]
    if len(trimmed) < int(0.85 * 16000):
        return None
    return trimmed


def write_s16_16k(path: Path, pcm: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    s16 = np.rint(np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(s16.tobytes())


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Prefer base wavs first, then _44k wavs whose base stem wasn't already added
    all_wavs = sorted(SAMPLES_DIR.glob("bailian-*.wav"))
    seen_stems = set()
    seen_audio_sig = set()
    clips = []
    for p in all_wavs:
        base_stem = p.stem.replace("_44k", "")
        if base_stem in seen_stems:
            continue
        pcm = read_any_wav_to_16k(p)
        if pcm is None:
            continue
        # Deduplicate near-identical audio by quantized energy profile + duration
        q_sig = (len(pcm) // 1600, round(float(np.sqrt(np.mean(pcm[:8000] ** 2))), 3), round(float(np.sqrt(np.mean(pcm[-8000:] ** 2))), 3))
        if q_sig in seen_audio_sig:
            continue
        seen_stems.add(base_stem)
        seen_audio_sig.add(q_sig)
        clips.append((p.name, pcm))

    total_unique_sec = sum(len(c[1]) / 16000.0 for c in clips)
    rng = random.Random(20261113)
    rng.shuffle(clips)

    # Hold out ~22s of unseen utterances for strict unseen validation & final preview!
    val_parts = [np.zeros(int(0.8 * 16000), np.float32)]
    val_sec = 0.8
    idx = 0
    val_pauses = [0.35, 0.75, 0.45, 0.85, 0.40, 0.90]
    p_i = 0
    while idx < len(clips) and val_sec < 21.5:
        name, pcm = clips[idx]
        idx += 1
        pause_s = val_pauses[p_i % len(val_pauses)]
        p_i += 1
        val_parts.append(pcm)
        val_parts.append(np.zeros(int(pause_s * 16000), np.float32))
        val_sec += (len(pcm) / 16000.0) + pause_s

    val_pcm = np.concatenate(val_parts)
    val_pcm = np.pad(val_pcm, (0, (-len(val_pcm)) % 640))
    val_path = OUT_DIR / "val_unseen_16k.wav"
    write_s16_16k(val_path, val_pcm)

    # Build 272.0s (4.53 min = 6,800 frames @ 25fps) training master audio
    train_parts = [np.zeros(int(0.8 * 16000), np.float32)]
    train_sec = 0.8
    pause_cycle = [0.24, 0.42, 0.76, 0.32, 0.92, 0.28, 0.68, 1.08]
    t_i = 0
    target_sec = 272.0
    pool = clips[idx:]
    pool_cursor = 0
    while train_sec < target_sec:
        name, pcm = pool[pool_cursor % len(pool)]
        pool_cursor += 1
        pause_s = pause_cycle[t_i % len(pause_cycle)]
        t_i += 1
        train_parts.append(pcm)
        train_parts.append(np.zeros(int(pause_s * 16000), np.float32))
        train_sec += (len(pcm) / 16000.0) + pause_s

    train_pcm = np.concatenate(train_parts)
    exact_samples = 6800 * 640
    if len(train_pcm) >= exact_samples:
        train_pcm = train_pcm[:exact_samples]
        train_pcm[-6400:] *= np.linspace(1.0, 0.0, 6400, dtype=np.float32)
        train_pcm[-3200:] = 0.0
    else:
        train_pcm = np.pad(train_pcm, (0, exact_samples - len(train_pcm)))

    train_path = OUT_DIR / "train_master_16k.wav"
    write_s16_16k(train_path, train_pcm)

    summary = {
        "unique_valid_clips_found": len(clips),
        "unique_speech_seconds": round(total_unique_sec, 2),
        "train_seconds": round(len(train_pcm) / 16000.0, 2),
        "train_frames_25fps": len(train_pcm) // 640,
        "val_seconds": round(len(val_pcm) / 16000.0, 2),
        "val_frames_25fps": len(val_pcm) // 640,
        "val_frames_50fps": len(val_pcm) // 320,
        "train_wav": str(train_path),
        "val_wav": str(val_path),
    }
    (OUT_DIR / "audio_dataset_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MASTER_AUDIO_READY_V2", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
