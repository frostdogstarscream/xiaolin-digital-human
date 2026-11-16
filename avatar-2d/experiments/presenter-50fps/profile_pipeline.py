import time,json
import engine50 as engine
import torch,numpy as np
from av import VideoFrame
assets=engine.Assets();p=engine.Presenter(engine.options('profile50'),assets,lambda x:None)
rows=[]
for batch in (4,8,16):
    tokens=[('idle',i) for i in range(batch)];features=np.ones((batch,80,16),np.float32)
    p._infer(tokens,features)
    measurements=[]
    for _ in range(10):
        a=time.perf_counter();pred=p._infer(tokens,features);b=time.perf_counter()
        frames=[p._compose(token,pred[i]) for i,token in enumerate(tokens)];c=time.perf_counter()
        converted=[VideoFrame.from_ndarray(frame,format='bgr24').reformat(format='yuv420p') for frame in frames];d=time.perf_counter()
        measurements.append([(b-a)/batch,(c-b)/batch,(d-c)/batch])
    mean=np.mean(measurements,axis=0)
    rows.append(dict(batch=batch,infer_ms=mean[0]*1000,compose_ms=mean[1]*1000,convert_ms=mean[2]*1000,serial_fps=1/sum(mean)))
    print(json.dumps(rows[-1]),flush=True)
(engine.ROOT/'outputs/presenter-50fps/pipeline-profile.json').write_text(json.dumps(rows,indent=2))
