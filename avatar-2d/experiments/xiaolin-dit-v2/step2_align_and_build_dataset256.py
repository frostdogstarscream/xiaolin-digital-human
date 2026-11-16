"""Step 2: Sub-pixel Skull-Locked Alignment of 512x512 Sonic DiT Teacher onto Multi-Pose
1080x1920 Full-Body Clips + 256x256 Dual-Reference Dataset Construction.

Key innovations over distill-v1:
  1. Teacher is 512x512 CVPR-2025 Sonic global-audio diffusion (crisp individual teeth, natural
     apple-muscle & nasolabial fold compression, realistic jaw kinematics) instead of zero-shot MuseTalk/Wav2Lip.
  2. Zero-drift Upper-Skull Similarity Lock (YoloFace 5-pt + PyrLK RANSAC on rigid forehead/brow/eye-corner/
     nose-bridge anchors) maps 512x512 Sonic frames onto every pose of idle, welcome-wave, explain-open-palms,
     and acknowledge-nod with sub-pixel accuracy and per-frame Lab skin-tone matching.
  3. Whole-lower-half anatomical BiSeNet union blending (covering apple muscles + nasolabial folds + lips +
     teeth + dynamic jaw/neck boundary) eliminates both double-chin ghosting and cheek-seam creases.
"""
import argparse
import json
import math
import os
import sys
import time
import wave
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path(r"F:\xiaolin\app"))
    ap.add_argument("--dit-dir", type=Path, default=Path(r"F:\xiaolin\dit-distill-v2"))
    return ap.parse_args()


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


def load_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def compute_speech_gate_25fps(pcm_16k: np.ndarray, n_frames: int) -> np.ndarray:
    """Smooth speech activity envelope at 25fps:
    - 1.0 during active phonation and short intra-sentence stops (< 0.36s = 9 frames) so Sonic's
      natural consonant closures and inter-word breathing play unaltered!
    - Smooth cosine ease to 0.0 only on long full-sentence silences (>= 0.44s = 11 frames).
    """
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = pcm_16k[i * 640 : (i + 1) * 640]
        if len(seg) > 0:
            rms[i] = float(np.sqrt(np.mean(seg ** 2)))
    voiced = (rms > 0.0045).astype(np.int32)

    # Bridge gaps shorter than 10 frames (400ms) so Sonic handles natural intra-clause articulation
    active = voiced.copy()
    i = 0
    while i < n_frames:
        if active[i] == 0:
            j = i
            while j < n_frames and active[j] == 0:
                j += 1
            if i > 0 and j < n_frames and (j - i) <= 10:
                active[i:j] = 1
            i = j
        else:
            i += 1

    # Dilate by 3 frames before speech onset (120ms pre-articulation) and 4 frames after offset
    kern = np.ones(8, dtype=np.int32)
    dil = (np.convolve(active, kern, mode="same") > 0).astype(np.float32)

    # Smooth 7-frame Hann window for zero-pop transitions into/out of long silences
    win = np.hanning(15).astype(np.float32)
    win /= win.sum()
    gate = np.convolve(np.pad(dil, (7, 7), mode="edge"), win, mode="valid")
    return np.clip(gate, 0.0, 1.0).astype(np.float32)


def extract_whisper_windows_25fps(audio_processor, audio_16k: np.ndarray, n_frames_25fps: int) -> np.ndarray:
    total_w = n_frames_25fps * 2 + 20
    ext_audio = np.pad(audio_16k, (3200 + 32000, 3200 + 32000))
    pieces = []
    for w0 in range(0, total_w, 1000):
        w1 = min(total_w, w0 + 1000)
        pcm_win = ext_audio[w0 * 320 : (w1 + 200) * 320]
        feat = audio_processor.audio2feat(pcm_win)
        pieces.append(feat[100 : 100 + (w1 - w0)])
    whisper_all = np.concatenate(pieces, axis=0)
    assert whisper_all.shape[0] == total_w, (whisper_all.shape, total_w)

    windows = np.empty((n_frames_25fps, 10, 5, 384), dtype=np.float16)
    for i in range(n_frames_25fps):
        c = 10 + i * 2
        windows[i] = whisper_all[c - 4 : c + 6].astype(np.float16)
    return windows


def parse_bisenet_512(parser, bgr_512: np.ndarray) -> np.ndarray:
    """Returns uint8 semantic class map (512, 512) using MuseTalk's BiSeNet:
    1:skin, 2:l_brow, 3:r_brow, 4:l_eye, 5:r_eye, 10:nose, 11:mouth(teeth/inner),
    12:u_lip, 13:l_lip, 14:neck, 16:cloth, 17:hair
    """
    pil_rgb = Image.fromarray(bgr_512[:, :, ::-1])
    with torch.inference_mode():
        inp = parser.preprocess(pil_rgb).unsqueeze(0).to("cuda")
        out = parser.net(inp)[0]
        seg = out.squeeze(0).argmax(0).cpu().numpy().astype(np.uint8)
    return seg


def build_upper_skull_anchor_points(canon_bgr_512: np.ndarray, canon_seg_512: np.ndarray, kps5: np.ndarray) -> np.ndarray:
    """Builds dense rigid upper-skull tracking points on canonical 512x512 portrait:
    Strictly restricted to forehead, eyebrow ridge, eye corners (excluding eyeball interior),
    and upper nasal bridge above y = nose_tip_y - 14.
    """
    H, W = canon_bgr_512.shape[:2]
    nose_y = float(kps5[2, 1])
    upper_mask = np.isin(canon_seg_512, [1, 2, 3, 10]).astype(np.uint8)
    # Exclude eyeballs (4, 5) + 6px eyelid margin so blinks never perturb skull pose!
    eyes_dil = cv2.dilate(np.isin(canon_seg_512, [4, 5]).astype(np.uint8), np.ones((13, 13), np.uint8))
    upper_mask[eyes_dil > 0] = 0
    # Strictly above mid-nose so cheek/apple-muscle motion never leaks into skull pose!
    cut_y = int(round(nose_y - 12))
    upper_mask[cut_y:, :] = 0
    upper_mask[: int(H * 0.14), :] = 0

    gray = cv2.cvtColor(canon_bgr_512, cv2.COLOR_BGR2GRAY)
    pts = cv2.goodFeaturesToTrack(gray, maxCorners=220, qualityLevel=0.01, minDistance=5, mask=upper_mask)
    # Always include outer/inner eye regions and glabella grid points
    eye_l, eye_r = kps5[0], kps5[1]
    glabella = 0.5 * (eye_l + eye_r)
    extra = np.array([
        eye_l + [-16, 0], eye_l + [16, 0],
        eye_r + [-16, 0], eye_r + [16, 0],
        glabella, glabella + [0, -18], glabella + [0, 14],
    ], dtype=np.float32).reshape(-1, 1, 2)
    if pts is None:
        return extra
    return np.concatenate([pts.astype(np.float32), extra], axis=0)


def align_to_canonical_512(
    src_bgr_512: np.ndarray,
    src_kps5: np.ndarray | None,
    canon_gray_512: np.ndarray,
    canon_kps5: np.ndarray,
    canon_anchor_pts: np.ndarray,
) -> np.ndarray:
    """Computes 2x3 Similarity Transform warping src_bgr_512 INTO canonical_512 skull coordinates."""
    # Step 1: Coarse similarity from 3 rigid points (left_eye, right_eye, glabella/upper-nose)
    if src_kps5 is not None:
        p_src3 = np.array([src_kps5[0], src_kps5[1], 0.65 * (src_kps5[0] + src_kps5[1]) + 0.35 * src_kps5[2]], dtype=np.float32)
        p_dst3 = np.array([canon_kps5[0], canon_kps5[1], 0.65 * (canon_kps5[0] + canon_kps5[1]) + 0.35 * canon_kps5[2]], dtype=np.float32)
        M_coarse, _ = cv2.estimateAffinePartial2D(p_src3, p_dst3, method=cv2.LMEDS)
    else:
        M_coarse = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    if M_coarse is None:
        M_coarse = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    pre_warped = cv2.warpAffine(src_bgr_512, M_coarse, (512, 512), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    pre_gray = cv2.cvtColor(pre_warped, cv2.COLOR_BGR2GRAY)

    # Step 2: Sub-pixel PyrLK optical flow refinement on rigid upper-skull anchors
    p1, st, _ = cv2.calcOpticalFlowPyrLK(
        canon_gray_512, pre_gray, canon_anchor_pts, None,
        winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if p1 is not None and st is not None:
        p_back, st_b, _ = cv2.calcOpticalFlowPyrLK(
            pre_gray, canon_gray_512, p1, None,
            winSize=(21, 21), maxLevel=3,
        )
        fb_err = np.linalg.norm((canon_anchor_pts - p_back).reshape(-1, 2), axis=1)
        good = (st.reshape(-1) == 1) & (st_b.reshape(-1) == 1) & (fb_err < 1.5)
        if int(good.sum()) >= 12:
            M_ref, _ = cv2.estimateAffinePartial2D(
                p1[good].reshape(-1, 2),
                canon_anchor_pts[good].reshape(-1, 2),
                method=cv2.RANSAC,
                ransacReprojThreshold=1.5,
            )
            if M_ref is not None:
                # Compose M_total = M_ref @ M_coarse
                A_c = np.vstack([M_coarse, [0, 0, 1]])
                A_r = np.vstack([M_ref, [0, 0, 1]])
                A_tot = A_r @ A_c
                return A_tot[:2].astype(np.float32)

    return M_coarse.astype(np.float32)


def invert_affine_2x3(M: np.ndarray) -> np.ndarray:
    A = np.vstack([M, [0.0, 0.0, 1.0]])
    return np.linalg.inv(A)[:2].astype(np.float32)


def compose_sonic_onto_pose_512(
    pose_crop_512: np.ndarray,
    pose_seg_512: np.ndarray,
    sonic_aligned_to_pose_512: np.ndarray,
    sonic_seg_in_pose_512: np.ndarray,
    nose_bridge_y: float,
    gate: float,
) -> np.ndarray:
    """Blends skull-locked Sonic 512x512 whole-lower-face (apple muscles + nasolabial +
    mouth + crisp teeth + moving jaw) onto pose_crop_512 with local Lab luminance/chroma matching.
    """
    if gate <= 1e-3:
        return pose_crop_512

    # 1. Local upper-cheek / nose-bridge Lab transfer so Sonic matches pose frame's exact lighting
    ref_zone = np.isin(pose_seg_512, [1, 10]) & np.isin(sonic_seg_in_pose_512, [1, 10])
    yy, xx = np.mgrid[0:512, 0:512]
    ref_zone = ref_zone & (yy >= int(nose_bridge_y - 18)) & (yy <= int(nose_bridge_y + 28))
    sonic_adj = sonic_aligned_to_pose_512.copy()
    if int(ref_zone.sum()) > 200:
        lab_p = cv2.cvtColor(pose_crop_512, cv2.COLOR_BGR2LAB).astype(np.float32)
        lab_s = cv2.cvtColor(sonic_adj, cv2.COLOR_BGR2LAB).astype(np.float32)
        delta = np.median(lab_p[ref_zone] - lab_s[ref_zone], axis=0)
        delta = np.clip(delta, [-12.0, -6.0, -6.0], [12.0, 6.0, 6.0])
        face_skin = np.isin(sonic_seg_in_pose_512, [1, 10, 12, 13])
        # Do NOT shift inner-mouth white teeth (class 11) chrominance! Only match skin & lips gently
        teeth_mask = (sonic_seg_in_pose_512 == 11).astype(np.float32)
        teeth_soft = cv2.GaussianBlur(teeth_mask, (9, 9), 0)[..., None]
        lab_shifted = np.clip(lab_s + delta.reshape(1, 1, 3), 0, 255)
        lab_final = lab_shifted * (1.0 - 0.85 * teeth_soft) + lab_s * (0.85 * teeth_soft)
        sonic_adj = cv2.cvtColor(lab_final.astype(np.uint8), cv2.COLOR_LAB2BGR)

    # 2. Semantic union mask of lower face (skin + nose tip + lips + inner mouth/teeth)
    face_classes = [1, 10, 11, 12, 13]
    union_face = (np.isin(pose_seg_512, face_classes) | np.isin(sonic_seg_in_pose_512, face_classes)).astype(np.float32)
    # Exclude hair (17) and collar/cloth (16) from pose frame if hair overlaps outer cheek
    hair_guard = cv2.GaussianBlur((pose_seg_512 == 17).astype(np.float32), (11, 11), 0)
    union_face = union_face * (1.0 - 0.85 * hair_guard)

    # Smooth horizontal transition across infraorbital / upper apple-muscle line
    top_y = nose_bridge_y - 6.0
    top_ramp = np.clip((yy.astype(np.float32) - top_y) / 30.0, 0.0, 1.0)
    border = np.minimum(np.minimum(xx, 511 - xx), np.minimum(yy, 511 - yy)).astype(np.float32)
    edge_ramp = np.clip(border / 24.0, 0.0, 1.0)

    raw_mask = cv2.GaussianBlur(union_face, (25, 25), 7.0) * top_ramp * edge_ramp
    alpha = (np.clip(raw_mask, 0.0, 1.0) * float(gate))[..., None]
    out = np.rint(sonic_adj.astype(np.float32) * alpha + pose_crop_512.astype(np.float32) * (1.0 - alpha))
    return np.clip(out, 0, 255).astype(np.uint8)


def ping_pong(lo: int, hi: int) -> list[int]:
    return list(range(lo, hi + 1)) + list(range(hi - 1, lo, -1))


def build_multipose_schedule(n_frames: int) -> list[tuple[str, int]]:
    """Cycles across ALL 5 clips including welcome-wave and goodbye-wave so Student learns
    exact upper-cheek lighting/expression compatibility across every gesture!
    """
    blocks = [
        [("idle", i) for i in ping_pong(104, 260)],               # 312f
        [("welcome-wave", i) for i in ping_pong(0, 174)],         # 348f
        [("idle", i) for i in ping_pong(488, 620)],               # 264f
        [("explain-open-palms", i) for i in ping_pong(0, 174)],   # 348f
        [("acknowledge-nod", i) for i in ping_pong(0, 98)],       # 196f
        [("goodbye-wave", i) for i in ping_pong(0, 174)],         # 348f
    ]
    cycle = [tok for blk in blocks for tok in blk]
    out = []
    while len(out) < n_frames:
        out.extend(cycle)
    return out[:n_frames]


def get_sonic_square_crop_box(idle_box_y1y2x1x2, frame_shape=(1920, 1080)) -> list[int]:
    """Square head-and-shoulders crop around Xiaolin's head in 1080x1920 (~384x384 -> 512x512)."""
    H, W = frame_shape[:2]
    y1, y2, x1, x2 = idle_box_y1y2x1x2
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2) + 8.0
    half = 192
    sx1 = max(0, int(round(cx - half)))
    sy1 = max(0, int(round(cy - half)))
    sx2 = min(W, sx1 + 2 * half)
    sy2 = min(H, sy1 + 2 * half)
    return [sx1, sy1, sx2, sy2]


def main():
    t0 = time.perf_counter()
    args = parse_args()
    WORKSPACE = args.workspace.resolve()
    DIT_DIR = args.dit_dir.resolve()
    SONIC_DIR = DIT_DIR / "vendor" / "Sonic"
    TEACHER_DIR = DIT_DIR / "teacher"
    DATASET_DIR = DIT_DIR / "dataset256"
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    AVATAR_ROOT = WORKSPACE / "avatar-2d"
    MUSE_ROOT = WORKSPACE / "musetalk-eval"
    VENDOR_ROOT = AVATAR_ROOT / "vendor" / "LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"

    sys.path.insert(0, str(AVATAR_ROOT / "tools"))
    from windows_runtime import prepare_runtime
    prepare_runtime()

    sys.path.insert(0, str(DIT_DIR / "pylibs"))
    sys.path.insert(0, str(DIT_DIR))
    sys.path.insert(0, str(SONIC_DIR))
    sys.path.insert(0, str(VENDOR_ROOT))

    from grade_presenter_v2 import cheek_color, grade
    from xiaolin_student256_gan import get_student_box256
    from src.dataset.face_align.align import AlignImage

    prev_cwd = Path.cwd()
    os.chdir(MUSE_ROOT)
    try:
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        from avatars.musetalk.utils.face_parsing import FaceParsing
        audio_processor = Audio2Feature(model_path=str(MUSE_ROOT / "models/whisper"))
        parser = FaceParsing(left_cheek_width=90, right_cheek_width=90)
    finally:
        os.chdir(prev_cwd)

    face_det = AlignImage("cuda", det_path=str(SONIC_DIR / "checkpoints" / "yoloface_v5m.pt"))

    # Load audio & Sonic Teacher 512x512 videos generated in Step 1
    train_wav = TEACHER_DIR / "train_64s_16k.wav"
    val_wav = TEACHER_DIR / "val_16s_16k.wav"
    train_sonic_mp4 = TEACHER_DIR / "sonic_train_64s_512.mp4"
    val_sonic_mp4 = TEACHER_DIR / "sonic_val_16s_512.mp4"

    train_pcm = load_wav_16k(train_wav)
    val_pcm = load_wav_16k(val_wav)

    def read_video_frames(mp4_path: Path) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(mp4_path))
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            if f.shape[:2] != (512, 512):
                f = cv2.resize(f, (512, 512), interpolation=cv2.INTER_LANCZOS4)
            frames.append(f)
        cap.release()
        return frames

    sonic_train_frames = read_video_frames(train_sonic_mp4)
    sonic_val_frames = read_video_frames(val_sonic_mp4)
    n_train = min(len(train_pcm) // 640, len(sonic_train_frames))
    n_val = min(len(val_pcm) // 640, len(sonic_val_frames))
    train_pcm = train_pcm[: n_train * 640]
    val_pcm = val_pcm[: n_val * 640]
    sonic_train_frames = sonic_train_frames[:n_train]
    sonic_val_frames = sonic_val_frames[:n_val]
    print(f"[Step2] Aligned lengths: train={n_train} frames ({n_train/25:.2f}s), val={n_val} frames ({n_val/25:.2f}s)", flush=True)

    train_gate = compute_speech_gate_25fps(train_pcm, n_train)
    val_gate = compute_speech_gate_25fps(val_pcm, n_val)

    print("[Step2] Extracting 50Hz Whisper encoder windows...", flush=True)
    train_whisper = extract_whisper_windows_25fps(audio_processor, train_pcm, n_train)
    val_whisper = extract_whisper_windows_25fps(audio_processor, val_pcm, n_val)
    np.save(DATASET_DIR / "train_whisper.npy", train_whisper)
    np.save(DATASET_DIR / "val_whisper.npy", val_whisper)

    # Load all 5 presenter-v2-1080 base clips & Lab-match skin tone to idle
    all_clips = ["idle", "welcome-wave", "explain-open-palms", "acknowledge-nod", "goodbye-wave"]
    train_sched = build_multipose_schedule(n_train)
    # Build unseen validation schedule explicitly testing idle -> welcome-wave -> explain-open-palms -> acknowledge-nod!
    val_sched = (
        [("idle", 120 + i) for i in range(65)]
        + [("welcome-wave", min(174, i)) for i in range(135)]
        + [("idle", 500 + i) for i in range(50)]
        + [("explain-open-palms", min(174, i)) for i in range(150)]
    )[:n_val]

    needed: dict[str, set[int]] = {c: set() for c in all_clips}
    for cid, fidx in train_sched + val_sched + [("idle", 150), ("welcome-wave", 85)]:
        needed[cid].add(fidx)
    for k in np.linspace(0, 749, 11).astype(int):
        needed["idle"].add(int(k))

    def load_clip_frames(cid: str, idx_set: set[int], corr=None):
        vpath = AVATAR_ROOT / "assets/presenter-v2-1080/prepared" / f"{cid}.mp4"
        cpath = AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / cid / "coords.json"
        coords = json.loads(cpath.read_text(encoding="utf-8"))
        cap = cv2.VideoCapture(str(vpath))
        out_f = {}
        mx = max(idx_set)
        i = 0
        while i <= mx:
            ok, fr = cap.read()
            if not ok:
                break
            if i in idx_set:
                if corr is not None:
                    fr = grade(fr, corr)
                out_f[i] = fr
            i += 1
        cap.release()
        return out_f, coords

    idle_f, idle_c = load_clip_frames("idle", needed["idle"], corr=None)
    ref_lab = np.median([cheek_color(idle_f[int(k)], idle_c[int(k)]) for k in np.linspace(0, 749, 11).astype(int)], axis=0)
    clip_frames = {"idle": idle_f}
    clip_coords = {"idle": idle_c}
    lab_corrs = {"idle": [0.0, 0.0, 0.0]}

    for cid in all_clips[1:]:
        cpath = AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / cid / "coords.json"
        ac = json.loads(cpath.read_text(encoding="utf-8"))
        s_idx = set(int(k) for k in np.linspace(0, len(ac) - 1, 11).astype(int))
        raw_s, _ = load_clip_frames(cid, s_idx, corr=None)
        b_lab = np.median([cheek_color(raw_s[k], ac[k]) for k in sorted(s_idx)], axis=0)
        corr = (ref_lab - b_lab).astype(np.float32)
        lab_corrs[cid] = corr.tolist()
        clip_frames[cid], clip_coords[cid] = load_clip_frames(cid, needed[cid] | s_idx, corr=corr)
        print(f"  Loaded & Lab-matched {cid}: {len(clip_frames[cid])} frames (corr={np.round(corr, 2).tolist()})", flush=True)

    # Canonical 512x512 skull template from idle#150 (exact crop fed to Sonic in Step 1!)
    canon_sq_box = get_sonic_square_crop_box(clip_coords["idle"][150], clip_frames["idle"][150].shape)
    csx1, csy1, csx2, csy2 = canon_sq_box
    canon_512 = cv2.imread(str(TEACHER_DIR / "canonical_portrait_512.png"))
    if canon_512 is None:
        canon_512 = cv2.resize(clip_frames["idle"][150][csy1:csy2, csx1:csx2], (512, 512), interpolation=cv2.INTER_LANCZOS4)
    canon_gray = cv2.cvtColor(canon_512, cv2.COLOR_BGR2GRAY)
    canon_seg = parse_bisenet_512(parser, canon_512)
    kps_list, _, _ = face_det(canon_512, maxface=True)
    canon_kps5 = kps_list[0].astype(np.float32)
    canon_anchors = build_upper_skull_anchor_points(canon_512, canon_seg, canon_kps5)
    canon_nose_bridge_y = float(0.60 * (canon_kps5[0, 1] + canon_kps5[1, 1]) * 0.5 + 0.40 * canon_kps5[2, 1])

    # Precompute pose -> canonical_512 transforms & BiSeNet masks for all unique base tokens!
    unique_tokens = sorted(set(train_sched + val_sched + [("idle", 150), ("welcome-wave", 85)]))
    print(f"[Step2] Precomputing skull-lock transforms & BiSeNet maps for {len(unique_tokens)} unique base frames...", flush=True)
    pose_meta = {}
    raw_wave85_crop = None
    raw_wave85_seg = None
    raw_wave85_M = None

    for tok in unique_tokens:
        cid, fidx = tok
        fr = clip_frames[cid][fidx]
        sq = get_sonic_square_crop_box(clip_coords[cid][fidx], fr.shape)
        sx1, sy1, sx2, sy2 = sq
        crop_512 = cv2.resize(fr[sy1:sy2, sx1:sx2], (512, 512), interpolation=cv2.INTER_LANCZOS4)
        seg_512 = parse_bisenet_512(parser, crop_512)
        kl, _, _ = face_det(crop_512, maxface=True)
        kp = kl[0].astype(np.float32) if len(kl) > 0 else None
        M_pose_to_canon = align_to_canonical_512(crop_512, kp, canon_gray, canon_kps5, canon_anchors)
        M_canon_to_pose = invert_affine_2x3(M_pose_to_canon)
        nb_y = float(0.60 * (kp[0, 1] + kp[1, 1]) * 0.5 + 0.40 * kp[2, 1]) if kp is not None else canon_nose_bridge_y

        if tok == ("welcome-wave", 85):
            raw_wave85_crop = crop_512.copy()
            raw_wave85_seg = seg_512.copy()
            raw_wave85_M = M_pose_to_canon.copy()

        # On grinning action clips (welcome-wave, goodbye-wave), harmonize the resting base frame across the
        # ENTIRE lower half of the face (apple muscles + nasolabial folds + mouth + chin) using skull-locked
        # canon_512 so silent frames never pop back to bared teeth AND cheeks match resting lips seamlessly!
        if cid in ("welcome-wave", "goodbye-wave"):
            canon_in_pose = cv2.warpAffine(canon_512, M_canon_to_pose, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
            canon_seg_in_pose = cv2.warpAffine(canon_seg, M_canon_to_pose, (512, 512), flags=cv2.INTER_NEAREST)
            harm_512 = compose_sonic_onto_pose_512(crop_512, seg_512, canon_in_pose, canon_seg_in_pose, nb_y, gate=1.0)
            fr_harm = fr.copy()
            fr_harm[sy1:sy2, sx1:sx2] = cv2.resize(harm_512, (sx2 - sx1, sy2 - sy1), interpolation=cv2.INTER_LANCZOS4)
            clip_frames[cid][fidx] = fr_harm
            crop_512 = harm_512
            seg_512 = parse_bisenet_512(parser, crop_512)

        pose_meta[tok] = (sq, crop_512, seg_512, M_pose_to_canon, M_canon_to_pose, nb_y)

    # Extract Dual Canonical References in Student 256x256 space:
    # 1) canonical_closed_ref_256 from idle#150
    b256_idle = get_student_box256(clip_coords["idle"][150], clip_frames["idle"][150].shape)
    closed_ref_256 = cv2.resize(
        clip_frames["idle"][150][b256_idle[1]:b256_idle[3], b256_idle[0]:b256_idle[2]],
        (256, 256), interpolation=cv2.INTER_LANCZOS4,
    )

    # 2) canonical_teeth_ref_256: pick the sharpest open-mouth teeth frame from Sonic Teacher,
    #    skull-stabilized onto idle#150 so closed_ref_256 & teeth_ref_256 are 100% skull-aligned!
    best_teeth_score = -1.0
    best_sonic_teeth_frame_1080 = None
    for sf in sonic_train_frames[::2]:
        s_seg = parse_bisenet_512(parser, sf)
        inner_mouth_px = int((s_seg == 11).sum())
        if inner_mouth_px < 450:
            continue
        kl, _, _ = face_det(sf, maxface=True)
        kp = kl[0].astype(np.float32) if len(kl) > 0 else None
        M_s2c = align_to_canonical_512(sf, kp, canon_gray, canon_kps5, canon_anchors)
        sf_canon = cv2.warpAffine(sf, M_s2c, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        s_seg_c = cv2.warpAffine(s_seg, M_s2c, (512, 512), flags=cv2.INTER_NEAREST)
        m_roi = sf_canon[s_seg_c == 11]
        sharp = float(cv2.Laplacian(cv2.cvtColor(sf_canon, cv2.COLOR_BGR2GRAY), cv2.CV_32F)[s_seg_c == 11].var()) if len(m_roi) > 50 else 0.0
        bright = float(np.percentile(m_roi, 85)) if len(m_roi) > 50 else 0.0
        score = sharp * (1.0 + bright / 128.0) * min(inner_mouth_px / 900.0, 1.5)
        if score > best_teeth_score:
            best_teeth_score = score
            comp_512 = compose_sonic_onto_pose_512(canon_512, canon_seg, sf_canon, s_seg_c, canon_nose_bridge_y, gate=1.0)
            f1080 = clip_frames["idle"][150].copy()
            f1080[csy1:csy2, csx1:csx2] = cv2.resize(comp_512, (csx2 - csx1, csy2 - csy1), interpolation=cv2.INTER_LANCZOS4)
            best_sonic_teeth_frame_1080 = f1080

    if best_sonic_teeth_frame_1080 is None and raw_wave85_crop is not None:
        # Fallback to real teeth in raw welcome-wave#85 skull-aligned to idle#150
        w_canon = cv2.warpAffine(raw_wave85_crop, raw_wave85_M, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        seg_wc = cv2.warpAffine(raw_wave85_seg, raw_wave85_M, (512, 512), flags=cv2.INTER_NEAREST)
        comp_512 = compose_sonic_onto_pose_512(canon_512, canon_seg, w_canon, seg_wc, canon_nose_bridge_y, gate=1.0)
        best_sonic_teeth_frame_1080 = clip_frames["idle"][150].copy()
        best_sonic_teeth_frame_1080[csy1:csy2, csx1:csx2] = cv2.resize(comp_512, (csx2 - csx1, csy2 - csy1), interpolation=cv2.INTER_LANCZOS4)

    teeth_ref_256 = cv2.resize(
        best_sonic_teeth_frame_1080[b256_idle[1]:b256_idle[3], b256_idle[0]:b256_idle[2]],
        (256, 256), interpolation=cv2.INTER_LANCZOS4,
    )
    np.save(DATASET_DIR / "canonical_closed_ref_256.npy", closed_ref_256)
    np.save(DATASET_DIR / "canonical_teeth_ref_256.npy", teeth_ref_256)
    imwrite_unicode(DATASET_DIR / "dual_refs_256.png", np.hstack([closed_ref_256, teeth_ref_256]), ".png")

    def build_split(split_name: str, sonic_frames: list[np.ndarray], sched: list[tuple[str, int]], gate_arr: np.ndarray, save_teacher_mp4: Path | None = None):
        n = len(sched)
        src_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_src_256.npy", mode="w+", dtype=np.uint8, shape=(n, 256, 256, 3))
        tgt_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_tgt_256.npy", mode="w+", dtype=np.uint8, shape=(n, 256, 256, 3))
        teacher_full_frames = [] if save_teacher_mp4 is not None else None

        for i in range(n):
            tok = sched[i]
            cid, fidx = tok
            base_1080 = clip_frames[cid][fidx]
            b256 = get_student_box256(clip_coords[cid][fidx], base_1080.shape)
            bx1, by1, bx2, by2 = b256
            src_mm[i] = cv2.resize(base_1080[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4)

            g = float(gate_arr[i])
            if g <= 1e-3:
                tgt_1080 = base_1080
            else:
                sf = sonic_frames[i]
                kl, _, _ = face_det(sf, maxface=True)
                kp = kl[0].astype(np.float32) if len(kl) > 0 else None
                M_s2c = align_to_canonical_512(sf, kp, canon_gray, canon_kps5, canon_anchors)
                sq, pose_512, pose_seg_512, _, M_c2p, nb_y = pose_meta[tok]
                # Compose M_sonic_to_pose = M_canon_to_pose @ M_sonic_to_canon
                A_s2c = np.vstack([M_s2c, [0, 0, 1]])
                A_c2p = np.vstack([M_c2p, [0, 0, 1]])
                M_s2p = (A_c2p @ A_s2c)[:2].astype(np.float32)

                sf_in_pose = cv2.warpAffine(sf, M_s2p, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
                s_seg_in_pose = parse_bisenet_512(parser, sf_in_pose)
                comp_512 = compose_sonic_onto_pose_512(pose_512, pose_seg_512, sf_in_pose, s_seg_in_pose, nb_y, gate=g)

                sx1, sy1, sx2, sy2 = sq
                tgt_1080 = base_1080.copy()
                tgt_1080[sy1:sy2, sx1:sx2] = cv2.resize(comp_512, (sx2 - sx1, sy2 - sy1), interpolation=cv2.INTER_LANCZOS4)

            tgt_mm[i] = cv2.resize(tgt_1080[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            if teacher_full_frames is not None:
                teacher_full_frames.append(tgt_1080)

            if (i + 1) % 250 == 0 or (i + 1) == n:
                print(f"  [{split_name}] {i+1}/{n} aligned & composed", flush=True)

        src_mm.flush()
        tgt_mm.flush()

        if save_teacher_mp4 is not None and teacher_full_frames:
            import subprocess
            ffmpeg = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"
            save_teacher_mp4.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                str(ffmpeg), "-v", "error", "-nostdin", "-y",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", "1080x1920", "-r", "25", "-i", "pipe:0",
                "-i", str(val_wav),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                str(save_teacher_mp4),
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            for fr in teacher_full_frames:
                proc.stdin.write(fr.tobytes())
            proc.stdin.close()
            proc.wait()

    build_split("train", sonic_train_frames, train_sched, train_gate, save_teacher_mp4=None)
    build_split("val", sonic_val_frames, val_sched, val_gate, save_teacher_mp4=DIT_DIR / "outputs" / "teacher_sonic_val_16s_fullbody_25fps.mp4")

    # Save visual inspection sheet of aligned 256x256 Sonic Teacher pairs across poses!
    val_s = np.load(DATASET_DIR / "val_src_256.npy", mmap_mode="r")
    val_t = np.load(DATASET_DIR / "val_tgt_256.npy", mmap_mode="r")
    cols = []
    for k in np.linspace(8, n_val - 12, 10).astype(int):
        cid, _ = val_sched[int(k)]
        top = val_s[int(k)].copy()
        bot = val_t[int(k)].copy()
        cv2.putText(top, f"Base: {cid}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 255), 1, cv2.LINE_AA)
        cv2.putText(bot, f"Sonic f={k}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 240, 120), 1, cv2.LINE_AA)
        cols.append(np.vstack([top, bot]))
    imwrite_unicode(DATASET_DIR / "sonic_aligned_256_samples.jpg", np.hstack(cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    summary = {
        "train_frames": n_train,
        "val_frames": n_val,
        "best_teeth_score": round(best_teeth_score, 2),
        "wall_seconds": round(time.perf_counter() - t0, 2),
    }
    (DATASET_DIR / "dataset256_meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP2_DATASET256_COMPLETE", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
