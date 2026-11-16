"""Xiaolin-DiT-Student-256:
Person-specific 256x256 Dual-Reference (Closed + Real Open-Teeth) ResUNet with
Multi-Scale Whisper-50Hz Spatial + FiLM Conditioning and Spectral-Norm PatchGAN Discriminator.

Designed to:
  1. Reconstruct full lower-half face (apple muscles + nasolabial folds + lips + crisp teeth + dynamic chin)
  2. Sustain >150 FPS FP16 natively on a single cloud Tesla T4 (50fps target) and >400 FPS on RTX 4090.
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils import spectral_norm


def get_student_box256(coord_y1y2x1x2, frame_shape=(1920, 1080)) -> list[int]:
    """Canonical crop box for 256x256 full-face + apple-muscle + dynamic-jaw ROI.
    Native coords in 1080x1920 are ~153w x 220h; expanding x by +-22 and y by [-4, +24]
    yields ~197w x 248h (~1:1 native pixel density at 256x256, zero downsampling blur).
    """
    H, W = frame_shape[:2]
    y1, y2, x1, x2 = coord_y1y2x1x2
    return [max(0, int(x1) - 22), max(0, int(y1) - 4), min(W, int(x2) + 22), min(H, int(y2) + 24)]


def build_lower_half_hide_mask_256() -> np.ndarray:
    """Smooth anatomical V-tapered mask in 256x256 box256 coordinates hiding the ENTIRE dynamic
    lower half of the face: apple muscles (cheeks below eyes), nasolabial folds,
    mouth/teeth, and moving chin/jawline, while keeping eyes, eyebrows, upper nose bridge,
    side hair outside the V-jawline, and neck/collar border intact for pose & lighting conditioning.
    Returns float32 array (256, 256, 1) in [0, 1] where 1 = masked out.
    """
    yy, xx = np.mgrid[0:256, 0:256].astype(np.float32)
    cx, cy = 128.0, 166.0
    # Full 90px half-width across cheekbones/apple-muscles (y<=154), tapering smoothly to 65px along V-jawline
    jaw_taper = np.clip((yy - 154.0) / 82.0, 0.0, 1.0)
    rx = 90.0 - 25.0 * jaw_taper
    ry = 72.0
    dist = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    hide = np.clip((1.12 - dist) / 0.34, 0.0, 1.0)
    # Protect eyes & upper nose bridge strictly above y=96
    top_cut = np.clip((yy - 96.0) / 18.0, 0.0, 1.0)
    # Protect bottom collar/neck border for seamless vertical jaw anchoring
    bot_cut = np.clip((245.0 - yy) / 11.0, 0.0, 1.0)
    side_cut = np.clip(np.minimum(xx - 20.0, 236.0 - xx) / 14.0, 0.0, 1.0)
    mask_f = (hide * top_cut * bot_cut * side_cut).astype(np.float32)
    return mask_f[..., None]


def build_lower_half_compose_alpha_256() -> np.ndarray:
    """Smooth V-tapered composition alpha in 256x256 box256 coordinates for pasting predicted
    apple muscles + nasolabial folds + mouth/teeth + dynamic chin onto the 1080x1920 frame.
    Hugs cheekbones wide (rx=94) and tapers along the jawline (rx->68) so side hair has zero halo.
    """
    yy, xx = np.mgrid[0:256, 0:256].astype(np.float32)
    cx, cy = 128.0, 166.0
    jaw_taper = np.clip((yy - 152.0) / 84.0, 0.0, 1.0)
    rx = 94.0 - 26.0 * jaw_taper
    ry = 75.0
    dist = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    core = np.clip((1.14 - dist) / 0.38, 0.0, 1.0)
    top_ramp = np.clip((yy - 92.0) / 20.0, 0.0, 1.0)
    edge = np.minimum(np.minimum(xx, 255.0 - xx), np.minimum(yy, 255.0 - yy))
    border_ramp = np.clip(edge / 14.0, 0.0, 1.0)
    alpha = (core * top_ramp * border_ramp).astype(np.float32)
    return alpha[..., None]


def build_degrin_mask_256() -> np.ndarray:
    """Soft inner-mouth/lip guard (256, 256, 1) used only when harmonizing raw bared-teeth action clips."""
    yy, xx = np.mgrid[0:256, 0:256].astype(np.float32)
    dist = ((xx - 128.0) / 68.0) ** 2 + ((yy - 168.0) / 42.0) ** 2
    return np.clip((1.10 - dist) / 0.35, 0.0, 1.0).astype(np.float32)[..., None]


class ResConvStage(nn.Module):
    """Tensor-Core-optimal 3x3 residual block (FP16 HMMA friendly on T4 & 4090)."""
    def __init__(self, in_ch: int, out_ch: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, kernel_size=3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.SiLU(inplace=True),
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(out_ch, out_ch, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
        )
        if stride != 1 or in_ch != out_ch:
            self.skip = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(out_ch),
            )
        else:
            self.skip = nn.Identity()
        self.act = nn.SiLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.conv2(self.conv1(x)) + self.skip(x))


class AudioFiLMUpStage(nn.Module):
    """Decoder upsampling stage with optional Audio FiLM (scale & shift) modulation
    so high-frequency articulatory features sharpen lip & tooth edges at 32x32 and 64x64.
    """
    def __init__(self, in_ch_cat: int, out_ch: int, audio_dim: int = 0):
        super().__init__()
        self.conv = ResConvStage(in_ch_cat, out_ch, stride=1)
        if audio_dim > 0:
            self.film = nn.Linear(audio_dim, out_ch * 2)
            nn.init.zeros_(self.film.weight)
            nn.init.zeros_(self.film.bias)
        else:
            self.film = None

    def forward(self, x_low: torch.Tensor, x_skip: torch.Tensor, audio_vec: torch.Tensor | None = None) -> torch.Tensor:
        x_up = F.interpolate(x_low, size=x_skip.shape[-2:], mode="bilinear", align_corners=False)
        h = self.conv(torch.cat([x_up, x_skip], dim=1))
        if self.film is not None and audio_vec is not None:
            gb = self.film(audio_vec).unsqueeze(-1).unsqueeze(-1)
            gamma, beta = gb.chunk(2, dim=1)
            h = h * (1.0 + 0.5 * torch.tanh(gamma)) + 0.5 * beta
        return h


class WhisperDualProjector(nn.Module):
    """Encodes Whisper-tiny 50Hz window (B, 10, 5, 384) into:
      1) Spatial 16x16 articulatory feature map (B, spatial_ch, 16, 16)
      2) Global frame-exact articulatory embedding (B, vec_dim) for FiLM modulation.
    """
    def __init__(self, spatial_ch: int = 256, vec_dim: int = 256):
        super().__init__()
        self.layer_mix = nn.Parameter(torch.zeros(5))
        self.layer_proj = nn.Sequential(
            nn.Linear(384, 96, bias=False),
            nn.LayerNorm(96),
            nn.SiLU(inplace=True),
        )
        self.temporal = nn.Sequential(
            nn.Conv1d(96 * 5, 320, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm1d(320),
            nn.SiLU(inplace=True),
            nn.Conv1d(320, 320, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm1d(320),
            nn.SiLU(inplace=True),
            nn.Conv1d(320, 256, kernel_size=3, stride=2, padding=1, bias=False),  # 10 -> 5
            nn.BatchNorm1d(256),
            nn.SiLU(inplace=True),
        )
        self.to_vec = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 5, vec_dim),
            nn.LayerNorm(vec_dim),
            nn.SiLU(inplace=True),
        )
        self.to_spatial_seed = nn.Sequential(
            nn.Linear(vec_dim, 256 * 4 * 4),
            nn.SiLU(inplace=True),
        )
        self.spatial_up = nn.Sequential(
            nn.ConvTranspose2d(256, spatial_ch, kernel_size=4, stride=2, padding=1, bias=False),  # 4x4 -> 8x8
            nn.BatchNorm2d(spatial_ch),
            nn.SiLU(inplace=True),
            nn.ConvTranspose2d(spatial_ch, spatial_ch, kernel_size=4, stride=2, padding=1, bias=False),  # 8x8 -> 16x16
            nn.BatchNorm2d(spatial_ch),
            nn.SiLU(inplace=True),
            ResConvStage(spatial_ch, spatial_ch, stride=1),
        )

    def forward(self, w: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        B = w.shape[0]
        weights = F.softmax(self.layer_mix, dim=0).view(1, 1, 5, 1)
        w_scaled = w * (0.5 + 2.5 * weights)
        w_proj = self.layer_proj(w_scaled)  # (B, 10, 5, 96)
        flat = w_proj.reshape(B, 10, 480).permute(0, 2, 1).contiguous()
        t = self.temporal(flat)             # (B, 256, 5)
        vec = self.to_vec(t)                # (B, vec_dim)
        seed = self.to_spatial_seed(vec).view(B, 256, 4, 4)
        spatial = self.spatial_up(seed)     # (B, spatial_ch, 16, 16)
        return spatial, vec


class XiaolinStudent256UNet(nn.Module):
    """9-channel 256x256 Dual-Ref UNet:
    Input channels: [masked_pose_bgr(3), canonical_closed_ref_bgr(3), canonical_teeth_ref_bgr(3)]
    """
    def __init__(self, in_channels: int = 9):
        super().__init__()
        ch = [32, 64, 128, 192, 256]
        self.inc = ResConvStage(in_channels, ch[0], stride=1)    # 256x256
        self.down1 = ResConvStage(ch[0], ch[1], stride=2)        # 128x128
        self.down2 = ResConvStage(ch[1], ch[2], stride=2)        # 64x64
        self.down3 = ResConvStage(ch[2], ch[3], stride=2)        # 32x32
        self.down4 = ResConvStage(ch[3], ch[4], stride=2)        # 16x16

        self.audio_proj = WhisperDualProjector(spatial_ch=ch[4], vec_dim=256)
        self.fuse = ResConvStage(ch[4] * 2, ch[4], stride=1)     # 16x16

        self.up1 = AudioFiLMUpStage(ch[4] + ch[3], ch[3], audio_dim=256)  # 32x32
        self.up2 = AudioFiLMUpStage(ch[3] + ch[2], ch[2], audio_dim=256)  # 64x64
        self.up3 = AudioFiLMUpStage(ch[2] + ch[1], ch[1], audio_dim=128 if False else 0)  # 128x128
        self.up4 = AudioFiLMUpStage(ch[1] + ch[0], ch[0], audio_dim=0)    # 256x256

        self.outc = nn.Sequential(
            nn.Conv2d(ch[0], ch[0], kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(ch[0]),
            nn.SiLU(inplace=True),
            nn.Conv2d(ch[0], 3, kernel_size=1, bias=True),
        )

    def forward(self, x: torch.Tensor, whisper_win: torch.Tensor) -> torch.Tensor:
        x1 = self.inc(x)         # (B, 32, 256, 256)
        x2 = self.down1(x1)      # (B, 64, 128, 128)
        x3 = self.down2(x2)      # (B, 128, 64, 64)
        x4 = self.down3(x3)      # (B, 192, 32, 32)
        x5 = self.down4(x4)      # (B, 256, 16, 16)

        a_spat, a_vec = self.audio_proj(whisper_win)
        f5 = self.fuse(torch.cat([x5, a_spat], dim=1))

        u1 = self.up1(f5, x4, a_vec)
        u2 = self.up2(u1, x3, a_vec)
        u3 = self.up3(u2, x2, None)
        u4 = self.up4(u3, x1, None)
        return torch.sigmoid(self.outc(u4))


class LowerFacePatchGANDiscriminator(nn.Module):
    """Spectral-Normalized Multi-Feature PatchGAN Discriminator focused on
    [y=84:244, x=24:232] (160x208 lower-half face: apple muscles + lips + teeth + jaw).
    Prevents L1 tooth-averaging blur and enforces crisp incisor & vermilion edges.
    """
    def __init__(self, in_channels: int = 6):
        super().__init__()
        self.b1 = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels, 64, kernel_size=4, stride=2, padding=1)),
            nn.LeakyReLU(0.2, inplace=True),
        )
        self.b2 = nn.Sequential(
            spectral_norm(nn.Conv2d(64, 128, kernel_size=4, stride=2, padding=1)),
            nn.LeakyReLU(0.2, inplace=True),
        )
        self.b3 = nn.Sequential(
            spectral_norm(nn.Conv2d(128, 256, kernel_size=4, stride=2, padding=1)),
            nn.LeakyReLU(0.2, inplace=True),
        )
        self.b4 = nn.Sequential(
            spectral_norm(nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1)),
            nn.LeakyReLU(0.2, inplace=True),
        )
        self.head = spectral_norm(nn.Conv2d(256, 1, kernel_size=3, stride=1, padding=1))

    def forward(self, img_256: torch.Tensor, cond_256: torch.Tensor) -> tuple[torch.Tensor, list[torch.Tensor]]:
        x = torch.cat([img_256[:, :, 84:244, 24:232], cond_256[:, :, 84:244, 24:232]], dim=1)
        f1 = self.b1(x)
        f2 = self.b2(f1)
        f3 = self.b3(f2)
        f4 = self.b4(f3)
        out = self.head(f4)
        return out, [f1, f2, f3, f4]
