"""Formal 50 fps Xiaolin-DiT-v2 (Sonic 512->256px Dual-Reference PatchGAN Student) + RIFE v4 renderer.
Compatible with BOTH Cloud Tesla T4 (gateway50.py) and Local LAN RTX 4090 (50fps WebRTC).

Key upgrades over ultralight-v1:
  - 256x256 (~1:1 native 1080x1920 pixel density) whole-lower-face ROI (apple muscles + nasolabial folds +
    vermilion lips + individual incisors + dynamic chin)
  - 9-channel Dual-Reference ResUNet (masked pose + closed ref + skull-locked HD open-teeth ref) + Audio-FiLM
  - V-tapered cheekbone-to-jawline composition mask with zero side-hair halo
  - >850 FPS FP16 on RTX 4090 and >240 FPS FP16 on single Cloud Tesla T4 (50fps target).
"""
import json
import os
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "presenter-v2-1080"))
DIT_ASSETS_DIR = Path(os.environ.get("XIAOLIN_DIT_V2_DIR", "/formal/dit-v2-assets"))
sys.path.insert(0, str(DIT_ASSETS_DIR))
sys.path.insert(0, str(HERE))

import live_engine_v2 as previous
import cv2
import numpy as np
import torch
from transformers import AutoFeatureExtractor, WhisperModel

cv2.setNumThreads(1)
from server import webrtc
from idle_scheduler import IdleScheduler
try:
    from render50_dit_v2 import render, LEFT_HIST_CHUNKS
except ImportError:
    from render50 import render, LEFT_HIST_CHUNKS
from xiaolin_student256_gan import (
    XiaolinStudent256UNet,
    get_student_box256,
    build_lower_half_hide_mask_256,
    build_lower_half_compose_alpha_256,
    build_degrin_mask_256,
)

ROOT = previous.ROOT
base = previous.base
webrtc.VIDEO_PTIME = 0.02


def desc(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(frame[80:1200, 250:830], (58, 112)).astype(np.float32)


class FastWhisper50Hz:
    """GPU-accelerated 50Hz Whisper-tiny encoder with dynamic-range calibration anchor at t=28.0s
    so quiet/silent streaming windows never suffer log_spec.max()-8.0 floor collapse.
    """
    def __init__(self, model_path: Path, device: str, dtype: torch.dtype):
        self.device = torch.device(device)
        self.dtype = dtype
        fe = AutoFeatureExtractor.from_pretrained(str(model_path), local_files_only=True)
        mel_fb = np.asarray(fe.mel_filters, dtype=np.float32)
        if mel_fb.shape == (201, 80):
            mel_fb = mel_fb.T.copy()
        self.mel_fb = torch.from_numpy(mel_fb).to(self.device)
        self.hann = torch.hann_window(400, device=self.device, dtype=torch.float32)

        self.whisper = WhisperModel.from_pretrained(str(model_path), local_files_only=True)
        self.whisper = self.whisper.to(device=self.device, dtype=self.dtype).eval()
        self.whisper.requires_grad_(False)

        cal_pcm = np.zeros(1600, dtype=np.float32)
        t_cal = np.arange(640, dtype=np.float32) / 16000.0
        cal_pcm[480:1120] = 0.28 * np.sin(2.0 * np.pi * 440.0 * t_cal)
        cal_stft = torch.stft(
            torch.from_numpy(cal_pcm).to(self.device),
            n_fft=400, hop_length=160, win_length=400,
            window=self.hann, center=True, pad_mode="reflect", return_complex=True,
        )
        self.cal_log_cols = (self.mel_fb @ cal_stft.abs()[:, :-1].pow(2)).clamp(min=1e-10).log10()
        self.cal_peak = float(self.cal_log_cols.max().item())

    @torch.inference_mode()
    def extract_batch_windows(self, pcm_1d: np.ndarray, batch_size: int = 4, center_start: int = LEFT_HIST_CHUNKS) -> torch.Tensor:
        wav_t = torch.from_numpy(pcm_1d).to(device=self.device, dtype=torch.float32)
        stft = torch.stft(
            wav_t, n_fft=400, hop_length=160, win_length=400,
            window=self.hann, center=True, pad_mode="reflect", return_complex=True,
        )
        log_spec = (self.mel_fb @ stft.abs()[:, :-1].pow(2)).clamp(min=1e-10).log10()
        gmax = torch.clamp(log_spec.max(), min=self.cal_peak)
        floor_min = gmax - 8.0
        floor_norm = (floor_min + 4.0) / 4.0

        norm_spec = (torch.maximum(log_spec, floor_min) + 4.0) / 4.0
        cal_norm = (torch.maximum(self.cal_log_cols, floor_min) + 4.0) / 4.0

        full_mel = torch.full((1, 80, 3000), float(floor_norm.item()), device=self.device, dtype=self.dtype)
        n_cols = min(2790, norm_spec.shape[1])
        full_mel[0, :, :n_cols] = norm_spec[:, :n_cols].to(self.dtype)
        full_mel[0, :, 2800 : 2800 + cal_norm.shape[1]] = cal_norm.to(self.dtype)

        hs = self.whisper.encoder(full_mel, output_hidden_states=True).hidden_states
        stacked = torch.stack(hs, dim=2)[0]
        wins = [stacked[center_start + i - 4 : center_start + i + 6] for i in range(batch_size)]
        return torch.stack(wins, dim=0)


def step_audio_packets50(self):
    for _ in range(self.batch_size):
        packet = self.get_audio_frame()
        self.frames.append(packet.data)
        self.output_queue.put(packet)
    pcm_window = np.concatenate(self.frames)
    self.feat_queue.put(pcm_window)
    self.frames = self.frames[-(LEFT_HIST_CHUNKS + self.stride_right_size) :]


class Assets:
    read = staticmethod(previous.Assets.read)

    def __init__(self):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        self.profile = json.loads((ROOT / "assets/presenter-v2-1080/profile.json").read_text(encoding="utf-8"))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" and os.environ.get("XIAOLIN_50_PRECISION", "fp16") == "fp16" else torch.float32
        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
        if self.device == "cuda":
            torch.backends.cudnn.benchmark = os.environ.get("XIAOLIN_CUDNN_BENCHMARK", "1") == "1"

        ckpt_path = Path(os.environ.get("XIAOLIN_DIT_V2_CKPT", str(DIT_ASSETS_DIR / "xiaolin_dit_student256_full_best.pth")))
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        self.model = XiaolinStudent256UNet(in_channels=9).to(device=self.device, dtype=self.dtype).eval()
        sd_key = "model_fp16" if "model_fp16" in ckpt else "state_dict"
        self.model.load_state_dict({k: v.to(device=self.device, dtype=self.dtype) for k, v in ckpt[sd_key].items()})

        closed_256 = ckpt["canonical_closed_ref_256"]
        teeth_256 = ckpt["canonical_teeth_ref_256"]
        self.closed_ref_t = (torch.from_numpy(closed_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.teeth_ref_t = (torch.from_numpy(teeth_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.dual_refs_t = torch.cat([self.closed_ref_t, self.teeth_ref_t], dim=1)  # (1, 6, 256, 256)

        self.hide_t = torch.from_numpy(build_lower_half_hide_mask_256().transpose(2, 0, 1)).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.compose_alpha_256 = build_lower_half_compose_alpha_256()  # (256, 256, 1)

        muse_root = Path(os.environ.get("MUSE_ROOT", "/muse"))
        self.whisper_50hz = FastWhisper50Hz(muse_root / "models/whisper", self.device, self.dtype)

        self.cache = Path(os.environ.get("XIAOLIN_MATERIAL_CACHE", str(ROOT / "runtime/presenter-50fps")))
        self.idle_plan = json.loads((self.cache / "idle-plan.json").read_text(encoding="utf-8"))
        self.transition_plan = json.loads((self.cache / "transition-plan.json").read_text(encoding="utf-8")) if (self.cache / "transition-plan.json").exists() else None

        self.full_frames = {}
        self.faces = {}
        self.clips = {}
        items = [self.profile["idle"], *self.profile["actions"]]
        if self.transition_plan:
            items.append({"id": "transitions"})
        for item in items:
            name = item["id"]
            directory = self.cache / name
            coords = json.loads((directory / "coords.json").read_text(encoding="utf-8"))
            self.clips[name] = (directory, coords)
            self.full_frames[name] = np.load(directory / "frames.npy", mmap_mode="r")
        self.start_descriptors = {
            s["start"]: desc(self.full_frames["idle"][s["start"]]) for s in self.idle_plan["segments"]
        }

        with torch.inference_mode():
            dummy_pcm = np.zeros((LEFT_HIST_CHUNKS + 10 + 4) * 320, dtype=np.float32)
            w_dummy = self.whisper_50hz.extract_batch_windows(dummy_pcm, batch_size=4)
            x_dummy = torch.zeros(4, 9, 256, 256, device=self.device, dtype=self.dtype)
            _ = self.model(x_dummy, w_dummy)
        if self.device == "cuda":
            torch.cuda.synchronize()

    def frame(self, name: str, index: int) -> np.ndarray:
        return self.full_frames[name][index]


class Presenter(previous.Presenter):
    def __init__(self, opt, assets: Assets, callback):
        super().__init__(opt, assets, callback)
        assert self.chunk == 320 and self.asr.chunk == 320
        self.asr.fps = 50
        self.asr.frames = [np.zeros(self.chunk, np.float32) for _ in range(LEFT_HIST_CHUNKS + self.opt.r)]
        self.asr.run_step = types.MethodType(step_audio_packets50, self.asr)

        self.idle_scheduler = IdleScheduler(assets.idle_plan["segments"], self._distance)
        self.stats.update(
            idle_segment_switches=0,
            video_fps=50,
            lipsync_model="xiaolin-dit-v2-256gan",
        )
        self.transitions = None
        if assets.transition_plan:
            from motion_transitions import MotionTransitions
            self.transitions = MotionTransitions(
                assets.transition_plan,
                self.idle_scheduler,
                {name: len(value[1]) for name, value in assets.clips.items()},
            )
            self.stats.update(
                material_version=assets.transition_plan["version"],
                transition_frames=0,
                actions_completed={name: 0 for name in assets.transition_plan["entries"]},
            )

        self._alpha_cache = {}
        self._post_speech_hold = 0

        def instrument(target, name, label):
            original = getattr(target, name)
            def measured(*args, **kwargs):
                began = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    self.stats[label + "_seconds"] = self.stats.get(label + "_seconds", 0.0) + time.perf_counter() - began
                    self.stats[label + "_calls"] = self.stats.get(label + "_calls", 0) + 1
            setattr(target, name, measured)

        for target, name, label in [
            (self.asr, "run_step", "mel"),
            (self, "_infer", "infer"),
            (self, "_compose", "compose"),
            (self.output, "push_video_frame", "push"),
        ]:
            instrument(target, name, label)

    def _infer(self, tokens, pcm_window: np.ndarray):
        started = time.perf_counter()
        B = len(tokens)
        crops = []
        for name, index in tokens:
            fr = self.assets.frame(name, index)
            bx1, by1, bx2, by2 = get_student_box256(self.assets.clips[name][1][index], fr.shape)
            crops.append(cv2.resize(fr[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LINEAR))

        with torch.inference_mode():
            w_batch = self.assets.whisper_50hz.extract_batch_windows(pcm_window, batch_size=B, center_start=LEFT_HIST_CHUNKS)
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).to(device=self.assets.device, dtype=self.assets.dtype) / 255.0
            inp = torch.cat([s_t * (1.0 - self.assets.hide_t), self.assets.dual_refs_t.expand(B, -1, -1, -1)], dim=1)
            pred_t = self.model(inp, w_batch)
            pred = (pred_t.float().clamp(0.0, 1.0) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        self.stats["inference_seconds"] += time.perf_counter() - started
        self.stats["inference_frames"] += B
        return pred

    def _compose(self, token, prediction, env_alpha: float = 1.0):
        name, index = token
        frame = self.assets.frame(name, index).copy()
        if prediction is not None and env_alpha > 1e-3:
            bx1, by1, bx2, by2 = get_student_box256(self.assets.clips[name][1][index], frame.shape)
            bw, bh = bx2 - bx1, by2 - by1
            key = (bh, bw)
            if key not in self._alpha_cache:
                self._alpha_cache[key] = cv2.resize(self.assets.compose_alpha_256, (bw, bh), interpolation=cv2.INTER_LINEAR)[..., None]
            alpha = self._alpha_cache[key] if env_alpha >= 0.999 else (self._alpha_cache[key] * float(env_alpha))
            patch = cv2.resize(prediction, (bw, bh), interpolation=cv2.INTER_LINEAR)
            frame[by1:by2, bx1:bx2] = (patch * alpha + frame[by1:by2, bx1:bx2] * (1.0 - alpha)).astype(np.uint8)
        return frame

    def _distance(self, token, index):
        return np.mean(np.abs(desc(self.assets.frame(*token)) - self.assets.start_descriptors[index]))

    def flush_talk(self, preserve_motion: bool = False):
        with self.lock:
            self.generation += 1
            self.reset_requested.set()
            self.preserve_motion_on_reset = preserve_motion
            self._post_speech_hold = 0
            self.motion_requested = None
            self.pending_audio.clear()
            base.clear_queue(self.asr.queue)
            if self.transitions:
                if not preserve_motion:
                    self.transitions.cancel_pending()
                self.preserve_motion_on_reset = preserve_motion or bool(self.transitions.action)
                self.motion = self.transitions.action
            elif not preserve_motion:
                self.motion = None
            player = getattr(self.output, "_player", None)
            if player is not None:
                base.clear_queue(player.audio._queue)
                base.clear_queue(player.video._queue)

    def _advance(self, packets):
        if self.transitions:
            from motion_transitions import advance
            with self.lock:
                return advance(self, packets)
        for packet in packets:
            info = packet.userdata
            if info.get("status") == "start" and info.get("action") in self.assets.clips and info["action"] != "idle":
                self.motion = info["action"]
                self.motion_index = 0
                self.stats["last_motion"] = self.motion
                info["motion_start"] = self.motion
        with self.lock:
            if self.motion_requested:
                self.motion = self.motion_requested
                self.motion_index = 0
                self.stats["last_motion"] = self.motion
                self.motion_requested = None
        if self.motion:
            self.pose = (self.motion, self.motion_index)
            self.motion_index += 1
            self.stats["motion_frames"] += 1
            if self.motion_index == len(self.assets.clips[self.motion][1]):
                self.motion = None
        else:
            index = self.idle_scheduler.next(self.pose, from_action=self.pose[0] != "idle")
            self.pose = ("idle", index)
            self.stats["idle_frames"] += 1
            self.stats["idle_loops"] = self.idle_scheduler.completed
            self.stats["idle_segment_switches"] = len(self.idle_scheduler.history)
        return self.pose

    render = render


options = previous.options
RTCManager = previous.RTCManager
session_manager = previous.session_manager
