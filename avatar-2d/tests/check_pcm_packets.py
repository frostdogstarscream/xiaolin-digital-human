"""Stateful resampling and native audio metadata across arbitrary PCM deltas."""
import asyncio
import faulthandler
faulthandler.dump_traceback_later(10,exit=True)
import audioop
import ast
import threading
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
from realtime_ingress import RealtimeIngress

# Load the actual queue method without importing/warming a GPU model.
tree=ast.parse((ROOT/'service/live_engine.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Presenter')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='enqueue_stream')
namespace={'np':np};exec(compile(ast.Module(body=[method],type_ignores=[]),'<native queue method>','exec'),namespace)


async def main():
    packets=[]
    class FakePresenter:
        enqueue_stream=namespace['enqueue_stream']
        chunk=320;generation=4;lock=threading.Lock()
        asr=SimpleNamespace(queue=SimpleNamespace(qsize=lambda:len(packets)),put_audio_frame=lambda w,m:packets.append((w.copy(),m)))
    class Ingress(RealtimeIngress):
        def public(self,job):return {}
        async def emit(self,*args,**kwargs):pass
    ingress=Ingress();ingress.presenter=FakePresenter();ingress.epoch=2;ingress.tts_token='test'
    job=dict(id='test',epoch=2,generation=4,seq=0,bytes=0,delta_count=0,pending=b'',rate_state=None,
             frame_started=False,status='preparing',action='welcome-wave')
    ingress.stream_jobs={'test':job}
    raw=(np.sin(np.arange(24001)*.12)*15000).astype('<i2').tobytes()
    class Request:
        headers={'X-Avatar-TTS':'test','X-Avatar-TTS-Job':'test'}
        data=b''
        async def read(self):return self.data
        async def json(self):return {'ok':True}
    req=Request();offset=0;index=0
    while offset<len(raw):
        size=[100,1512,4800,638][index%4]
        req.data=raw[offset:offset+size];req.headers['X-Avatar-TTS-Seq']=str(index)
        await ingress.tts_packet(req);offset+=len(req.data);index+=1
    await ingress.tts_end(req)
    expected=np.frombuffer(audioop.ratecv(raw,2,1,24000,16000,None)[0],dtype='<i2').astype(np.float32)/32768
    actual=np.concatenate([w for w,_ in packets])
    np.testing.assert_array_equal(actual[:len(expected)],expected)
    assert not np.any(actual[len(expected):]) and len(actual)-len(expected)<320
    assert sum(m.get('status')=='start' for _,m in packets)==1
    assert sum(bool(m.get('end')) for _,m in packets)==1 and packets[-1][1]['end']
    count=len(packets)
    ingress.presenter.generation+=1
    ingress.presenter.enqueue_stream(np.zeros(320,np.float32),{},generation=4)
    assert len(packets)==count,'Old generation must not enqueue audio'
    print('PASS arbitrary PCM boundaries, stateful 24k->16k resampling, single start/end, stale generation rejection')


if __name__=='__main__':
    try:asyncio.run(main())
    finally:faulthandler.cancel_dump_traceback_later()
