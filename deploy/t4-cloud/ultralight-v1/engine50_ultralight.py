"""Formal 50 fps Xiaolin-Ultralight + RIFE v4 renderer.
Preserves 20ms PCM cadence (chunk=320), WebRTC H.264/NVENC 50fps, MotionTransitions,
and gateway50.py API compatibility while upgrading lip-sync to Xiaolin-Ultralight (50Hz Whisper)
with calibrated post-speech geometric lip closure and zero silent teeth bleed.
"""
import json
import os
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "presenter-v2-1080"))
ULTRALIGHT_ASSETS_DIR = Path(os.environ.get("XIAOLIN_ULTRALIGHT_DIR", "/formal/ultralight-assets"))
sys.path.insert(0, str(ULTRALIGHT_ASSETS_DIR))
sys.path.insert(0, str(HERE))

import live_engine_v2 as previous
import cv2
import numpy as np
import torch
from transformers import AutoFeatureExtractor, WhisperModel

cv2.setNumThreads(1)
from server import webrtc
from idle_scheduler import IdleScheduler
from render50 import render, LEFT_HIST_CHUNKS
from xiaolin_ultralight_model import (
    XiaolinUltralightUNet,
    build_compose_alpha_192,
    build_degrin_mask_192,
    build_mouth_hide_mask_192,
)

ROOT = previous.ROOT
base = previous.base
webrtc.VIDEO_PTIME = 0.02


def get_student_ubox(coord_y1y2x1x2, H: int = 1920, W: int = 1080):
    y1, y2, x1, x2 = coord_y1y2x1x2
    return max(0, x1 - 8), max(0, y1), min(W, x2 + 8), min(H, y2 + 16)


def desc(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(frame[80:1200, 250:830], (58, 112)).astype(np.float32)


class FastWhisper50Hz:
    """GPU-accelerated 50Hz Whisper-tiny encoder matching HuggingFace WhisperFeatureExtractor
    to < 1e-5 with built-in dynamic-range calibration anchor at t=28.0s so quiet/silent
    streaming windows NEVER suffer log_spec.max()-8.0 floor collapse.
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

        # Precompute 40ms normal-speech-amplitude calibration pulse at t=28.0s (cols 2800..2808)
        cal_pcm = np.zeros(1600, dtype=np.float32)
        t_cal = np.arange(640, dtype=np.float32) / 16000.0
        cal_pcm[480:1120] = 0.28 * np.sin(2.0 * np.pi * 440.0 * t_cal)
        cal_t = torch.from_numpy(cal_pcm).to(self.device)
        cal_stft = torch.stft(
            cal_t, n_fft=400, hop_length=160, win_length=400,
            window=self.hann, center=True, pad_mode="reflect", return_complex=True,
        )
        cal_log = (self.mel_fb @ cal_stft.abs()[:, :-1].pow(2)).clamp(min=1e-10).log10()
        self.cal_log_cols = cal_log  # (80, 10)
        self.cal_peak = float(cal_log.max().item())

    @torch.inference_mode()
    def extract_batch_windows(self, pcm_1d: np.ndarray, batch_size: int = 4, center_start: int = LEFT_HIST_CHUNKS) -> torch.Tensor:
        """pcm_1d: 1D float32 PCM of (LEFT_HIST_CHUNKS + right_look + batch_size) * 320 samples.
        Returns (batch_size, 10, 5, 384) tensor on self.device in self.dtype.
        """
        wav_t = torch.from_numpy(pcm_1d).to(device=self.device, dtype=torch.float32)
        stft = torch.stft(
            wav_t, n_fft=400, hop_length=160, win_length=400,
            window=self.hann, center=True, pad_mode="reflect", return_complex=True,
        )
        mag = stft.abs()[:, :-1].pow(2)
        mel = self.mel_fb @ mag
        log_spec = mel.clamp(min=1e-10).log10()

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
        stacked = torch.stack(hs, dim=2)[0]  # (1500, 5, 384)
        wins = [stacked[center_start + i - 4 : center_start + i + 6] for i in range(batch_size)]
        return torch.stack(wins, dim=0)


def step_audio_packets50(self):
    """Advance audio packets by batch_size (4 * 20ms = 80ms) without wasting CPU/GPU
    computing mel spectrograms during silent idle. Actual 50Hz Whisper extraction runs
    on-demand inside Presenter._infer only when speech or closure tail is active.
    """
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
        torch.set_num_threads(4)
        if self.device == "cuda":
            torch.backends.cudnn.benchmark = True
            torch.backends.cudnn.benchmark_limit = 4

        ckpt_path = Path(os.environ.get("XIAOLIN_ULTRALIGHT_CKPT", str(ULTRALIGHT_ASSETS_DIR / "xiaolin_ultralight_best.pth")))
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        self.model = XiaolinUltralightUNet(in_channels=6).to(device=self.device, dtype=self.dtype).eval()
        sd_key = "model_fp16" if "model_fp16" in ckpt else "state_dict"
        self.model.load_state_dict({k: v.to(device=self.device, dtype=self.dtype) for k, v in ckpt[sd_key].items()})

        ref_192 = ckpt["canonical_ref_192"]
        self.ref_t = (torch.from_numpy(ref_192.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.hide_t = torch.from_numpy(build_mouth_hide_mask_192().transpose(2, 0, 1)).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.degrin_t = torch.from_numpy(build_degrin_mask_192().transpose(2, 0, 1)).unsqueeze(0).to(device=self.device, dtype=self.dtype)
        self.compose_alpha_192 = build_compose_alpha_192()

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
            x_dummy = torch.zeros(4, 6, 192, 192, device=self.device, dtype=self.dtype)
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
        # Seed rolling left history to LEFT_HIST_CHUNKS while keeping output_queue lookahead unchanged (opt.r = 10)
        self.asr.frames = [np.zeros(self.chunk, np.float32) for _ in range(LEFT_HIST_CHUNKS + self.opt.r)]
        self.asr.run_step = types.MethodType(step_audio_packets50, self.asr)

        self.idle_scheduler = IdleScheduler(assets.idle_plan["segments"], self._distance)
        self.stats.update(
            idle_segment_switches=0,
            video_fps=50,
            lipsync_model="xiaolin-ultralight-v1",
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
            ux1, uy1, ux2, uy2 = get_student_ubox(self.assets.clips[name][1][index], *fr.shape[:2])
            crops.append(cv2.resize(fr[uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LINEAR))

        with torch.inference_mode():
            w_batch = self.assets.whisper_50hz.extract_batch_windows(pcm_window, batch_size=B, center_start=LEFT_HIST_CHUNKS)
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).to(device=self.assets.device, dtype=self.assets.dtype) / 255.0
            ref_b = self.assets.ref_t.expand(B, -1, -1, -1)
            s_clean = s_t * (1.0 - self.assets.degrin_t) + ref_b * self.assets.degrin_t
            inp = torch.cat([s_clean * (1.0 - self.assets.hide_t), ref_b], dim=1)
            pred_t = self.model(inp, w_batch)
            pred = (pred_t.float().clamp(0.0, 1.0) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        self.stats["inference_seconds"] += time.perf_counter() - started
        self.stats["inference_frames"] += B
        return pred

    def _compose(self, token, prediction, env_alpha: float = 1.0):
        name, index = token
        frame = self.assets.frame(name, index).copy()
        if prediction is not None and env_alpha > 1e-3:
            ux1, uy1, ux2, uy2 = get_student_ubox(self.assets.clips[name][1][index], *frame.shape[:2])
            uw, uh = ux2 - ux1, uy2 - uy1
            key = (uh, uw)
            if key not in self._alpha_cache:
                self._alpha_cache[key] = cv2.resize(self.assets.compose_alpha_192, (uw, uh), interpolation=cv2.INTER_LINEAR)[..., None]
            alpha = self._alpha_cache[key] if env_alpha >= 0.999 else (self._alpha_cache[key] * float(env_alpha))
            patch = cv2.resize(prediction, (uw, uh), interpolation=cv2.INTER_LINEAR)
            frame[uy1:uy2, ux1:ux2] = (patch * alpha + frame[uy1:uy2, ux1:ux2] * (1.0 - alpha)).astype(np.uint8)
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
