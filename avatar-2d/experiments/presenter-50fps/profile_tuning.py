import time,json
import engine50 as engine
import torch,numpy as np
assets=engine.Assets();p=engine.Presenter(engine.options('tune50'),assets,lambda x:None)
tokens=[('idle',i) for i in range(4)];features=np.ones((4,80,16),np.float32)
reference=p._infer(tokens,features);rows=[]
for name,dtype,tune in [('fp32-tuned',torch.float32,True),('fp16-tuned',torch.float16,True)]:
    torch.backends.cudnn.benchmark=tune
    torch.backends.cudnn.benchmark_limit=4
    assets.dtype=dtype;assets.model=assets.model.to(dtype=dtype);p.model=assets.model
    p._infer(tokens,features)
    for batch in (4,8):
        ts=[('idle',i) for i in range(batch)];fs=np.ones((batch,80,16),np.float32)
        p._infer(ts,fs);times=[]
        for _ in range(20):
            a=time.perf_counter();pred=p._infer(ts,fs);times.append((time.perf_counter()-a)/batch)
        delta=np.abs(pred[:4].astype(np.float32)-reference.astype(np.float32))
        row=dict(mode=name,batch=batch,infer_ms=float(np.mean(times)*1000),pixel_mae=float(delta.mean()),pixel_max=float(delta.max()))
        rows.append(row);print(json.dumps(row),flush=True)
(engine.ROOT/'outputs/presenter-50fps/tuning-profile.json').write_text(json.dumps(rows,indent=2))
