"""Exercise real formal handlers/PCM/cache with an isolated non-GPU presenter."""
import asyncio
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'service'))
import app as legacy
from live_app import LiveBridge
from gesture_planner import ActionController

class Request:
    path='/api/chat'
    headers={'X-Avatar-Viewer':'test-owner','X-Avatar-TTS':'unit-token'}
    def __init__(self,data):self.data=data
    async def json(self):return self.data

class Ingress(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b=LiveBridge.__new__(LiveBridge);legacy.Bridge.__init__(self.b)
        b=self.b;b.actions=ActionController();b.actions.begin(0);b.voice_task=None;b.voice_turn=None
        b.voice_stage='idle';b.tts_token='unit-token';b.stream_jobs={};b.streamed_sources=Counter();b.playback_owner='test-owner'
        b.loop=asyncio.get_running_loop();b.rtc=SimpleNamespace(pcs=[SimpleNamespace(connectionState='connected')])
        self.queued=[];self.flushes=[]
        b.presenter=SimpleNamespace(generation=0,chunk=320,asr=SimpleNamespace(queue=SimpleNamespace(qsize=lambda:0)),
            flush_talk=lambda **kw:self.flushes.append(kw),enqueue=lambda w,m:self.queued.append(m),
            enqueue_stream=lambda w,m,**kw:self.queued.append((m,kw)))
    async def asyncTearDown(self):self.b.executor.shutdown(wait=True)
    def signal(self,gesture='acknowledge-nod',plan='p'):
        return dict(self.b.actions.context(self.b.epoch),gesture=gesture,plan_id=plan,conversation_id='conv-test')

    async def test_retired_endpoints_have_no_side_effect(self):
        application=web.Application();application.add_routes([web.post('/api/say',self.b.say),web.post('/api/action',self.b.action)])
        async with TestClient(TestServer(application)) as c:
            for route in ('say','action'):
                response=await c.post('/api/'+route,json={'text':'ignored','action':'welcome-wave'})
                self.assertEqual(response.status,410)
        self.assertEqual(self.b.epoch,0);self.assertFalse(self.queued);self.assertIsNone(self.b.actions.turn['reserved'])

    async def test_stream_and_cache_share_one_slot(self):
        signal=self.signal();data={'user':'Avatar2D','file':'bailian-realtime-'+'a'*32+'.wav',
            'text':'好的，收到。','conversation_id':'conv-test','action':signal}
        response=await self.b.tts_begin(Request(data));job=self.b.jobs[json.loads(response.text)['job_id']]
        self.b.enqueue_pcm(job,b'\0'*640);self.b.enqueue_pcm(job,b'\0'*640,end=True)
        self.assertEqual(sum(kw['start'] for _,kw in self.queued),1)
        self.assertTrue(all(m['turn_id']==signal['turn_id'] for m,_ in self.queued));self.queued.clear()
        # Another cached sentence in this same turn must remain idle, with metadata intact.
        with tempfile.TemporaryDirectory() as directory:
            samples=Path(directory)/'samples';samples.mkdir();source=samples/'unit.wav';source.write_bytes(b'unit')
            payload={'Topic':'human','Username':'Avatar2D','Data':{'Key':'audio','Value':str(source),'CONV_ID':'conv-test',
                'CONV_MSG_NO':2,'Text':'下一句话。','Action':signal}}
            with patch.object(legacy,'FAY',Path(directory)),patch.object(self.b,'decode_audio',return_value=np.zeros(320,np.float32)):
                await self.b.receive(payload)
        self.assertEqual(self.queued[0]['action'],'idle');self.assertEqual(self.queued[0]['plan_id'],'p')

    async def test_unbound_and_stale_audio_rejected(self):
        signal=self.signal();self.b.epoch+=1
        data={'user':'Avatar2D','file':'bailian-realtime-'+'a'*32+'.wav','text':'旧轮次',
              'conversation_id':'conv-test','action':signal}
        with self.assertRaises(web.HTTPConflict):await self.b.tts_begin(Request(data))
        self.assertFalse(self.b.jobs)
        with self.assertRaises(ValueError):self.b.audio_plan(self.signal(),'wrong-conversation')

    async def test_internal_handoff_preserves_motion_external_interrupt_cancels(self):
        self.b.voice_task=asyncio.current_task();turn=self.b.actions.turn['turn_id']
        await self.b.interrupt('new_turn')
        self.assertEqual(self.b.actions.turn['turn_id'],turn);self.assertEqual(self.flushes[-1],{'preserve_motion':True})
        self.b.voice_task=None;await self.b.interrupt('user')
        self.assertIsNone(self.b.actions.turn);self.assertEqual(self.flushes[-1],{'preserve_motion':False})

if __name__=='__main__':unittest.main(verbosity=2)
