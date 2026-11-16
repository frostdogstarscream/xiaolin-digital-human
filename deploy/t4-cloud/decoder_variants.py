"""Explicit lab-only decoder variants. The default remains original MuseTalk."""
import os
import numpy as np
import torch


def configure(assets, root):
    variant=os.environ.get('MUSE_DECODER_VARIANT','original')
    assets.decoder_variant=variant
    if variant=='original':return
    if variant=='compiled':
        assets.unet.model.forward=torch.compile(assets.unet.model.forward,mode='max-autotune-no-cudagraphs',fullgraph=True,dynamic=False)
        assets.vae.vae.decode=torch.compile(assets.vae.vae.decode,mode='max-autotune-no-cudagraphs',fullgraph=True,dynamic=False)
        return
    if variant!='taesd':raise ValueError('Unknown decoder variant: '+variant)
    from diffusers import AutoencoderTiny
    if not (root/'models/taesd/verified.json').exists():
        raise RuntimeError('Tiny decoder must be hash verified before use')
    tiny=AutoencoderTiny.from_pretrained(root/'models/taesd',torch_dtype=assets.dtype).to(assets.device).eval()
    assets.unet.model.to(memory_format=torch.channels_last)
    assets.tiny_decoder=tiny

    def decode(latents):
        # TAESD expects SD diffusion latents directly (scaling_factor=1).
        image=tiny.decode(latents.to(assets.dtype)).sample
        image=(image/2+.5).clamp(0,1)
        image=image.detach().cpu().permute(0,2,3,1).float().numpy()
        return (image*255).round().astype(np.uint8)[...,::-1]

    assets.vae.decode_latents=decode
