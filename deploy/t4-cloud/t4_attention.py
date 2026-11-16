"""Single-GPU Turing adapter preserving variable-length attention masks."""
import torch
import xformers.ops as xops


def flash_attention(q, k, v, q_lens=None, k_lens=None, dropout_p=0.,
                    softmax_scale=None, q_scale=None, causal=False,
                    window_size=(-1, -1), deterministic=False,
                    dtype=torch.float16, version=None):
    if window_size != (-1, -1):
        raise NotImplementedError('Local attention is outside this T4 evaluation')
    if causal and q.shape[1] != k.shape[1]:
        raise NotImplementedError('Unequal causal sequence lengths require separate validation')
    out = torch.zeros_like(q, dtype=q.dtype)
    for b in range(q.shape[0]):
        nq = int(q_lens[b]) if q_lens is not None else q.shape[1]
        nk = int(k_lens[b]) if k_lens is not None else k.shape[1]
        if nq == 0 or nk == 0:
            continue
        qb = q[b:b+1, :nq].to(torch.float16)
        kb = k[b:b+1, :nk].to(torch.float16)
        vb = v[b:b+1, :nk].to(torch.float16)
        if q_scale is not None:
            qb = qb * q_scale
        bias = xops.LowerTriangularMask() if causal else None
        out[b:b+1, :nq] = xops.memory_efficient_attention(
            qb, kb, vb, attn_bias=bias, p=dropout_p, scale=softmax_scale).to(out.dtype)
    return out
