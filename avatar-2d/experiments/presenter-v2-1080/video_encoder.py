"""Process-local 1080p H.264/NVENC adapter; no package or vendor files modified."""
import os,fractions
import av
from aiortc import codecs
from aiortc.codecs import h264

def configure():
    backend=os.environ.get('XIAOLIN_VIDEO_ENCODER','h264_nvenc')
    if backend not in ('libx264','h264_nvenc'):raise ValueError('Unsupported video encoder')
    h264.DEFAULT_BITRATE=4000000;h264.MAX_BITRATE=6000000
    original=h264.H264Encoder
    class Encoder1080(original):
        def _encode_frame(self,frame,force_keyframe):
            if self.codec and (self.codec.width!=frame.width or self.codec.height!=frame.height or abs(self.target_bitrate-self.codec.bit_rate)/self.codec.bit_rate>.1):
                self.buffer_data=b'';self.buffer_pts=None;self.codec=None
            frame.pict_type=av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE
            if self.codec is None:
                self.codec=av.CodecContext.create(backend,'w');self.codec.width=frame.width;self.codec.height=frame.height
                self.codec.bit_rate=self.target_bitrate;self.codec.pix_fmt='yuv420p'
                self.codec.framerate=fractions.Fraction(25);self.codec.time_base=fractions.Fraction(1,90000);self.codec.profile='Baseline'
                if backend=='h264_nvenc':
                    self.codec.options={'preset':'p4','tune':'ull','profile':'baseline','level':'4.0','rc':'cbr','zerolatency':'1','bf':'0','delay':'0','rc-lookahead':'0'}
                else:self.codec.options={'level':'40','tune':'zerolatency','preset':'veryfast'};self.codec.thread_count=4
            data=b''.join(bytes(packet) for packet in self.codec.encode(frame))
            if data:yield from self._split_bitstream(data)
    codecs.H264Encoder=Encoder1080
    for codec in codecs.CODECS['video']:
        if codec.mimeType.lower()=='video/h264':
            profile=codec.parameters.get('profile-level-id')
            if profile:codec.parameters['profile-level-id']=profile[:-2]+'28'
    return backend
