import fractions,json,time
import av,numpy as np,torch,psutil
start=time.monotonic()
assert torch.cuda.device_count()==1
a=torch.ones(128,128,device='cuda');assert (a@a)[0,0].item()==128
codec=av.CodecContext.create('h264_nvenc','w');codec.width=1080;codec.height=1920
codec.pix_fmt='yuv420p';codec.time_base=fractions.Fraction(1,25);codec.framerate=fractions.Fraction(25)
codec.options={'preset':'p4','tune':'ull','rc':'cbr','bf':'0','delay':'0','zerolatency':'1'}
codec.bit_rate=4000000
frame=av.VideoFrame.from_ndarray(np.zeros((1920,1080,3),np.uint8),format='bgr24');frame.pts=0
packets=codec.encode(frame);assert packets
print(json.dumps(dict(status='PASSED',gpu=torch.cuda.get_device_name(0),cuda_devices=torch.cuda.device_count(),
    nvenc_1080p_packet_bytes=sum(p.size for p in packets),seconds=time.monotonic()-start,psutil=psutil.__version__)),flush=True)
