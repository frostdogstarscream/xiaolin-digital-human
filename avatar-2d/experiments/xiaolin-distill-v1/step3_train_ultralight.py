"""Step 3 (Mouth Track): Train Xiaolin's exclusive lightweight real-time UNet
(XiaolinUltralightUNet, 192x192, ~4.5 MB FP16) on the 6,800-frame multi-pose Teacher v2 dataset.
Includes:
  - Masked pose-exact context + canonical closed-mouth reference (zero teeth-leakage from smiling clips)
  - 12% explicit multi-pose silent-identity pairing (guarantees silent Whisper -> exact closed-mouth smile)
  - Weighted Mouth/Teeth L1 + Sobel Edge Sharpness + Offline VGG16 Perceptual + 2-Frame Temporal Velocity Loss
  - Strict evaluation on the 574-frame unseen speech validation set + FP16 batch=4 speed benchmark.
"""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path("F:/xiaolin/app"))
    ap.add_argument("--distill-dir", type=Path, default=Path("F:/xiaolin/distill-v1"))
    ap.add_argument("--epochs", type=int, default=55)
    ap.add_argument("--batch-pairs", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1.2e-3)
    return ap.parse_args()


ARGS = parse_args()
WORKSPACE = ARGS.workspace.resolve()
DISTILL_DIR = ARGS.distill_dir.resolve()
DATASET_DIR = DISTILL_DIR / "dataset"
CKPT_DIR = DISTILL_DIR / "checkpoints"
AVATAR_ROOT = WORKSPACE / "avatar-2d"

sys.path.insert(0, str(AVATAR_ROOT / "tools"))
from windows_runtime import prepare_runtime
prepare_runtime()
sys.path.insert(0, str(DISTILL_DIR))

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models
from xiaolin_ultralight_model import (
    XiaolinUltralightUNet,
    build_mouth_hide_mask_192,
)


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


class OfflineVGGPerceptual(nn.Module):
    def __init__(self):
        super().__init__()
        vgg_ckpt = Path.home() / ".cache/torch/hub/checkpoints/vgg16-397923af.pth"
        vgg = models.vgg16(weights=None)
        if vgg_ckpt.exists():
            vgg.load_state_dict(torch.load(vgg_ckpt, map_location="cpu", weights_only=True))
        else:
            raise RuntimeError(f"Expected cached VGG16 weights at {vgg_ckpt}")
        feats = vgg.features
        self.s1 = nn.Sequential(*[feats[i] for i in range(4)]).eval()   # relu1_2
        self.s2 = nn.Sequential(*[feats[i] for i in range(4, 9)]).eval()  # relu2_2
        self.s3 = nn.Sequential(*[feats[i] for i in range(9, 16)]).eval() # relu3_3
        for p in self.parameters():
            p.requires_grad_(False)
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    def forward(self, pred_bgr: torch.Tensor, tgt_bgr: torch.Tensor) -> torch.Tensor:
        # Focus perceptual loss on lower-face mouth/teeth/jaw ROI [88:184, 24:168] (RGB order)
        p_rgb = pred_bgr[:, [2, 1, 0], 88:184, 24:168]
        t_rgb = tgt_bgr[:, [2, 1, 0], 88:184, 24:168]
        p = (p_rgb - self.mean) / self.std
        t = (t_rgb - self.mean) / self.std
        f1_p, f1_t = self.s1(p), self.s1(t)
        f2_p, f2_t = self.s2(f1_p), self.s2(f1_t)
        f3_p, f3_t = self.s3(f2_p), self.s3(f2_t)
        return F.l1_loss(f1_p, f1_t) + F.l1_loss(f2_p, f2_t) + 0.8 * F.l1_loss(f3_p, f3_t)


def sobel_edges(img: torch.Tensor) -> torch.Tensor:
    # img: (B, 3, H, W)
    kx = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=img.dtype, device=img.device).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
    ky = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=img.dtype, device=img.device).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
    gx = F.conv2d(img, kx, padding=1, groups=3)
    gy = F.conv2d(img, ky, padding=1, groups=3)
    return torch.cat([gx, gy], dim=1)


def main():
    t0 = time.perf_counter()
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(20261113)
    np.random.seed(20261113)
    torch.backends.cudnn.benchmark = False
    torch.cuda.set_per_process_memory_fraction(0.42)
    device = torch.device("cuda")

    print("Loading multi-pose master dataset into RAM for ultra-fast training...", flush=True)
    train_src = np.load(DATASET_DIR / "train_src_192.npy")    # (6800, 192, 192, 3) uint8
    train_tgt = np.load(DATASET_DIR / "train_tgt_192.npy")    # (6800, 192, 192, 3) uint8
    train_whisp = np.load(DATASET_DIR / "train_whisper.npy")  # (6800, 10, 5, 384) float16

    val_src = np.load(DATASET_DIR / "val_src_192.npy")
    val_tgt = np.load(DATASET_DIR / "val_tgt_192.npy")
    val_whisp = np.load(DATASET_DIR / "val_whisper.npy")
    canonical_ref = np.load(DATASET_DIR / "canonical_ref_192.npy")  # (192, 192, 3) uint8

    n_train = len(train_src)
    n_val = len(val_src)
    # Identify authentic silent frames in train_src==train_tgt (e.g. first 12 leading silent frames)
    silent_indices = [i for i in range(min(40, n_train)) if np.max(np.abs(train_src[i].astype(int) - train_tgt[i].astype(int))) == 0]
    if not silent_indices:
        silent_indices = [0, 1, 2]
    silent_whisp_pool = torch.from_numpy(train_whisp[silent_indices].astype(np.float32)).to(device)  # (S, 10, 5, 384)

    hide_mask_np = build_mouth_hide_mask_192()  # (192, 192, 1)
    hide_mask_t = torch.from_numpy(hide_mask_np.transpose(2, 0, 1)).unsqueeze(0).to(device)  # (1, 1, 192, 192)
    ref_t = (torch.from_numpy(canonical_ref.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device)  # (1, 3, 192, 192)

    # Spatial loss weight map emphasizing mouth/teeth/lips (12x) and dynamic jaw/chin (5x)
    yy, xx = np.mgrid[0:192, 0:192].astype(np.float32)
    jaw_roi = ((xx >= 24) & (xx <= 168) & (yy >= 94) & (yy <= 184)).astype(np.float32)
    teeth_roi = ((xx >= 46) & (xx <= 146) & (yy >= 108) & (yy <= 156)).astype(np.float32)
    jaw_roi = cv2.GaussianBlur(jaw_roi, (11, 11), 0)
    teeth_roi = cv2.GaussianBlur(teeth_roi, (9, 9), 0)
    pix_weight = torch.from_numpy(1.0 + 4.0 * jaw_roi + 9.0 * teeth_roi).view(1, 1, 192, 192).to(device)
    edge_weight = torch.from_numpy(0.2 + 2.5 * jaw_roi + 5.0 * teeth_roi).view(1, 1, 192, 192).to(device)

    model = XiaolinUltralightUNet(in_channels=6).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"XiaolinUltralightUNet parameters: {n_params:,} (~{n_params*2/1024**2:.2f} MB in FP16)", flush=True)

    vgg_loss_fn = OfflineVGGPerceptual().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=ARGS.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=ARGS.epochs, eta_min=2e-5)
    scaler = torch.amp.GradScaler("cuda")

    valid_pair_starts = np.arange(0, n_train - 1)
    batch_pairs = ARGS.batch_pairs

    best_val_mouth_l1 = 999.0
    history = []

    def evaluate_val():
        model.eval()
        tot_mse, tot_mouth_l1, tot_silent_l1, silent_cnt = 0.0, 0.0, 0.0, 0
        preds_out = []
        with torch.inference_mode(), torch.amp.autocast("cuda", dtype=torch.float16):
            for b0 in range(0, n_val, 64):
                b1 = min(n_val, b0 + 64)
                B = b1 - b0
                s = torch.from_numpy(val_src[b0:b1].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
                t = torch.from_numpy(val_tgt[b0:b1].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
                w = torch.from_numpy(val_whisp[b0:b1]).to(device, non_blocking=True).float()
                s_masked = s * (1.0 - hide_mask_t)
                inp = torch.cat([s_masked, ref_t.expand(B, -1, -1, -1)], dim=1)
                pred = model(inp, w).float()
                tot_mse += F.mse_loss(pred, t, reduction="sum").item() / (3 * 192 * 192)
                tot_mouth_l1 += torch.abs(pred[:, :, 104:172, 42:150] - t[:, :, 104:172, 42:150]).mean(dim=(1, 2, 3)).sum().item()
                # Check silent frames where target == source
                diff_ts = torch.abs(t - s).amax(dim=(1, 2, 3))
                sil_mask = diff_ts < 1e-4
                if sil_mask.any():
                    tot_silent_l1 += torch.abs(pred[sil_mask] - s[sil_mask]).mean(dim=(1, 2, 3)).sum().item()
                    silent_cnt += int(sil_mask.sum().item())
                preds_out.append((pred.clamp(0, 1) * 255.0).byte().cpu().numpy().transpose(0, 2, 3, 1))
        psnr = -10.0 * math.log10(max(1e-8, tot_mse / n_val))
        mouth_l1 = tot_mouth_l1 / n_val
        sil_l1 = tot_silent_l1 / max(1, silent_cnt)
        return psnr, mouth_l1, sil_l1, np.concatenate(preds_out, axis=0)

    for epoch in range(1, ARGS.epochs + 1):
        model.train()
        t_ep = time.perf_counter()
        perm = np.random.permutation(valid_pair_starts)
        ep_loss = 0.0
        steps = 0

        for p0 in range(0, len(perm), batch_pairs):
            idx0 = perm[p0 : p0 + batch_pairs]
            if len(idx0) < 4:
                continue
            idx1 = idx0 + 1
            P = len(idx0)

            s0 = torch.from_numpy(train_src[idx0].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
            s1 = torch.from_numpy(train_src[idx1].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
            t0_gt = torch.from_numpy(train_tgt[idx0].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
            t1_gt = torch.from_numpy(train_tgt[idx1].transpose(0, 3, 1, 2)).to(device, non_blocking=True).float() / 255.0
            w0 = torch.from_numpy(train_whisp[idx0]).to(device, non_blocking=True).float()
            w1 = torch.from_numpy(train_whisp[idx1]).to(device, non_blocking=True).float()

            # 12% explicit multi-pose silent-identity pairs: teach exact closed-mouth resting face across all poses!
            n_sil = max(1, int(0.12 * P))
            sil_pick = torch.randint(0, len(silent_whisp_pool), (n_sil,), device=device)
            w0[:n_sil] = silent_whisp_pool[sil_pick]
            w1[:n_sil] = silent_whisp_pool[sil_pick]
            t0_gt[:n_sil] = s0[:n_sil]
            t1_gt[:n_sil] = s1[:n_sil]

            # Subtle synchronous brightness/translation micro-augmentation (50% prob) for robustness on transition frames
            if np.random.rand() < 0.5:
                gain = torch.empty((P, 1, 1, 1), device=device).uniform_(0.97, 1.03)
                s0 = (s0 * gain).clamp(0, 1)
                s1 = (s1 * gain).clamp(0, 1)
                t0_gt = (t0_gt * gain).clamp(0, 1)
                t1_gt = (t1_gt * gain).clamp(0, 1)

            s_cat = torch.cat([s0, s1], dim=0)
            t_cat = torch.cat([t0_gt, t1_gt], dim=0)
            w_cat = torch.cat([w0, w1], dim=0)

            inp_cat = torch.cat([s_cat * (1.0 - hide_mask_t), ref_t.expand(2 * P, -1, -1, -1)], dim=1)

            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", dtype=torch.float16):
                pred_cat = model(inp_cat, w_cat)
                l_vgg = vgg_loss_fn(pred_cat, t_cat)
                pred_f = pred_cat.float()
                l_pix = (torch.abs(pred_f - t_cat) * pix_weight).mean()
                l_edge = (torch.abs(sobel_edges(pred_f) - sobel_edges(t_cat)) * edge_weight).mean()
                pred0, pred1 = pred_f[:P], pred_f[P:]
                vel_diff = torch.abs((pred1 - pred0) - (t1_gt - t0_gt)) * pix_weight
                l_temp = vel_diff.mean()
                loss = l_pix + 0.35 * l_edge + 0.12 * l_vgg.float() + 2.2 * l_temp

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            scaler.step(optimizer)
            scaler.update()
            ep_loss += loss.item()
            steps += 1
            if epoch == 1 and steps == 10:
                torch.cuda.synchronize()
                vram_mb = torch.cuda.max_memory_reserved() / (1024 ** 2)
                print(f"STEP_WARMUP step=10 elapsed={time.perf_counter()-t_ep:.2f}s peak_reserved_mb={vram_mb:.1f}", flush=True)

        scheduler.step()

        if epoch in (1, 2) or epoch % 5 == 0 or epoch == ARGS.epochs:
            psnr, mouth_l1, sil_l1, val_preds = evaluate_val()
            lr_now = scheduler.get_last_lr()[0]
            rec = {
                "epoch": epoch,
                "train_loss": round(ep_loss / max(1, steps), 4),
                "val_psnr_db": round(psnr, 2),
                "val_mouth_l1": round(mouth_l1, 5),
                "val_silent_l1": round(sil_l1, 5),
                "lr": round(lr_now, 6),
                "epoch_sec": round(time.perf_counter() - t_ep, 2),
            }
            history.append(rec)
            print("TRAIN_EPOCH", json.dumps(rec), flush=True)
            if mouth_l1 < best_val_mouth_l1:
                best_val_mouth_l1 = mouth_l1
                torch.save(
                    {
                        "model_fp16": {k: v.half().cpu() for k, v in model.state_dict().items()},
                        "canonical_ref_192": canonical_ref,
                        "epoch": epoch,
                        "val_psnr_db": psnr,
                        "val_mouth_l1": mouth_l1,
                    },
                    CKPT_DIR / "xiaolin_ultralight_best.pth",
                )
                # Save unseen validation visual comparison strip (Clean Base vs Teacher GT vs Student Pred)
                probe_ids = [5, 38, 62, 95, 145, 210, 310, 440]
                cols = []
                for pid in probe_ids:
                    if pid < len(val_preds):
                        col = np.vstack([val_src[pid], val_tgt[pid], val_preds[pid]])
                        cv2.putText(col, f"#{pid}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 240, 120), 1, cv2.LINE_AA)
                        cols.append(col)
                imwrite_unicode(CKPT_DIR / "val_unseen_student_vs_teacher.jpg", np.hstack(cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    # Speed benchmark in FP16 batch=4 (exact online 50fps engine batch size!)
    best_ckpt = torch.load(CKPT_DIR / "xiaolin_ultralight_best.pth", map_location="cpu", weights_only=False)
    model_fp16 = XiaolinUltralightUNet(in_channels=6).cuda().half().eval()
    model_fp16.load_state_dict({k: v.cuda().half() for k, v in best_ckpt["model_fp16"].items()})

    dummy_x = torch.randn(4, 6, 192, 192, device="cuda", dtype=torch.float16)
    dummy_w = torch.randn(4, 10, 5, 384, device="cuda", dtype=torch.float16)
    with torch.inference_mode():
        for _ in range(30):
            _ = model_fp16(dummy_x, dummy_w)
        torch.cuda.synchronize()
        t_b = time.perf_counter()
        iters = 200
        for _ in range(iters):
            _ = model_fp16(dummy_x, dummy_w)
        torch.cuda.synchronize()
        dt = time.perf_counter() - t_b

    batch4_ms = (dt / iters) * 1000.0
    fps_4090 = (iters * 4) / dt
    ckpt_mb = (CKPT_DIR / "xiaolin_ultralight_best.pth").stat().st_size / (1024 ** 2)

    summary = {
        "best_epoch": best_ckpt["epoch"],
        "best_val_psnr_db": round(float(best_ckpt["val_psnr_db"]), 2),
        "best_val_mouth_l1": round(float(best_ckpt["val_mouth_l1"]), 5),
        "checkpoint_path": str(CKPT_DIR / "xiaolin_ultralight_best.pth"),
        "checkpoint_size_mb": round(ckpt_mb, 2),
        "batch4_fp16_ms_4090": round(batch4_ms, 3),
        "unet_throughput_fps_4090": round(fps_4090, 1),
        "total_train_seconds": round(time.perf_counter() - t0, 2),
        "history": history,
    }
    (CKPT_DIR / "train_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP3_TRAIN_COMPLETE", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
