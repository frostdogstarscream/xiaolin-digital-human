"""No cloud calls: profile safety, TTS isolation, HTTP SSE and live LLM reload."""
import asyncio
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'service'))
import app
import bailian_speech
import provider_config as provider
from fay_llm_runtime import ReloadableLLM, make_llm, set_session


def seed(directory):
    path = Path(directory)/'system.conf'
    config = provider.read_config(path)
    config['key'].update(gpt_api_key='test-bailian-key', gpt_base_url=provider.PRESETS['bailian']['base_url'],
        gpt_model_engine='qwen-plus', tts_module='bailian', bailian_tts_realtime_enabled='true',
        bailian_tts_voice='Cherry', big_model_engine='', preserved_setting='untouched')
    provider.write_config(config, path)
    return path


class Profiles(unittest.TestCase):
    def test_dual_placeholder_pins_independent_role_and_can_disable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=seed(directory)
            original=provider.read_config(path)
            public=provider.set_collaboration('dual_primary_placeholder',path)
            self.assertEqual(public['collaboration']['mode'],'dual')
            self.assertTrue(public['collaboration']['same_model_placeholder'])
            self.assertNotIn('test-bailian-key',json.dumps(public))
            current=provider.read_config(path)
            self.assertEqual(current['key']['big_model_engine'],'qwen-plus')
            self.assertEqual(current['key']['big_model_api_key'],original['key']['gpt_api_key'])
            self.assertTrue(all(current['key'][name]==value for name,value in original['key'].items() if not name.startswith('big_model_')))
            provider.save_settings(dict(provider='custom',model='other-model',base_url='https://example.com/v1',api_key='different-test-key'),path)
            current=provider.read_config(path)
            self.assertEqual(current['key']['big_model_api_key'],'test-bailian-key')
            self.assertEqual(current['key']['big_model_base_url'],provider.PRESETS['bailian']['base_url'])
            self.assertFalse(provider.public_settings(path)['collaboration']['same_model_placeholder'])
            public=provider.set_collaboration('single',path)
            self.assertEqual(public['collaboration']['mode'],'single')
            self.assertEqual(provider.read_config(path)['key']['gpt_model_engine'],'other-model')

    def test_switch_and_restore_keeps_tts_and_unrelated_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = seed(directory)
            with patch.object(bailian_speech, 'FAY', Path(directory)):
                original_tts = bailian_speech.settings()
                public = provider.save_settings(dict(provider='opencode_go', **{k:provider.PRESETS['opencode_go'][k] for k in ('model','base_url')}, api_key='test-go-key'),path)
                self.assertEqual(public['model'], 'deepseek-v4.1-flash')
                self.assertNotIn('test-', json.dumps(public))
                self.assertEqual(bailian_speech.settings(), original_tts)
                config = provider.read_config(path)
                self.assertEqual(config['key']['preserved_setting'], 'untouched')
                provider.save_settings(dict(provider='bailian', **{k:provider.PRESETS['bailian'][k] for k in ('model','base_url')}),path)
                self.assertEqual(provider.read_config(path)['key']['gpt_api_key'], 'test-bailian-key')
                self.assertEqual(bailian_speech.settings(), original_tts)

    def test_cross_address_key_reuse_rejected_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = seed(directory)
            config = provider.read_config(path)
            for data in (
                dict(provider='custom',base_url='https://example.com/v1',model='company/deepseek:flash'),
                dict(provider='custom',base_url='http://example.com/v1',model='flash',api_key='test'),
                dict(provider='custom',base_url='https://user:pass@example.com/v1',model='flash',api_key='test'),
                dict(provider='custom',base_url='https://example.com/v1?key=bad',model='flash',api_key='test'),
                dict(provider='custom',base_url='https://example.com/v1',model='flash',api_key='test bad'),
            ):
                with self.assertRaises(provider.ConfigurationError):provider.resolve_submission(data, config)
            value=provider.resolve_submission(dict(provider='custom',base_url='http://127.0.0.1:1234/v1/chat/completions',model='company/deepseek:flash',api_key='EMPTY'),config)
            self.assertEqual(value['base_url'], 'http://127.0.0.1:1234/v1')
            self.assertEqual(value['model'], 'company/deepseek:flash')


class HTTPProbe(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=seed(self.temp.name)
        self.patch=patch.object(app,'FAY',Path(self.temp.name));self.patch.start()
        self.upstream_calls=[]
        async def complete(request):
            self.upstream_calls.append(dict(body=await request.json(),authorization=request.headers.get('Authorization')))
            if self.upstream_calls[-1]['body']['model']=='error':
                return web.json_response({'error':'private upstream credentials detail'},status=401)
            response=web.StreamResponse(headers={'Content-Type':'text/event-stream'})
            await response.prepare(request)
            for delta in ({'reasoning_content':'not speech'}, {'content':'连接'}, {'content':'成功'}):
                await response.write(('data: '+json.dumps({'choices':[{'delta':delta}]},ensure_ascii=False)+'\n\n').encode())
                await asyncio.sleep(.005)
            await response.write(b'data: [DONE]\n\n');await response.write_eof()
            return response
        upstream=web.Application();upstream.router.add_post('/v1/chat/completions',complete)
        self.server=TestServer(upstream);await self.server.start_server()
        self.bridge=app.Bridge();self.bridge.http=ClientSession(trust_env=False)
        application=web.Application(middlewares=[app.local_only])
        application.add_routes(app.provider_routes(self.bridge))
        application.router.add_post('/api/provider',self.bridge.configure)
        self.client=TestClient(TestServer(application));await self.client.start_server()
        self.data=dict(provider='custom',base_url=str(self.server.make_url('/v1')),model='org/flash',api_key='local-test')

    async def asyncTearDown(self):
        await self.client.close();await self.bridge.http.close();await self.server.close()
        self.bridge.executor.shutdown(wait=False);self.patch.stop();self.temp.cleanup()

    async def test_stream_probe_does_not_save_or_tts_and_errors_are_safe(self):
        before=self.path.read_bytes()
        response=await self.client.post('/api/provider-test',json=self.data,headers={'X-Avatar-Client':'1'})
        value=await response.json()
        self.assertEqual(response.status,200);self.assertEqual(value['reply'],'连接成功')
        self.assertFalse(value['saved']);self.assertFalse(value['tts_called'])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.upstream_calls[-1]['authorization'],'Bearer local-test')
        response=await self.client.post('/api/provider-test',json={**self.data,'model':'error'},headers={'X-Avatar-Client':'1'})
        value=await response.text()
        self.assertEqual(response.status,502);self.assertIn('401',value);self.assertNotIn('private',value)

    async def test_local_guards_and_redacted_profile_endpoint(self):
        response=await self.client.post('/api/provider',json=self.data)
        self.assertEqual(response.status,403)
        response=await self.client.post('/api/provider',json=self.data,headers={'X-Avatar-Client':'1','Origin':'https://unrelated.example'})
        self.assertEqual(response.status,403)
        response=await self.client.post('/api/provider',json=self.data,headers={'X-Avatar-Client':'1'})
        self.assertEqual(response.status,200)
        self.assertNotIn('local-test',await response.text())

    async def test_collaboration_endpoint_uses_native_switch_and_hides_keys(self):
        response=await self.client.post('/api/provider-collaboration',json={'mode':'dual_primary_placeholder'})
        self.assertEqual(response.status,403)
        response=await self.client.post('/api/provider-collaboration',json={'mode':'dual_primary_placeholder'},headers={'X-Avatar-Client':'1'})
        text=await response.text()
        self.assertEqual(response.status,200)
        self.assertNotIn('test-bailian-key',text)
        self.assertEqual(json.loads(text)['provider']['collaboration']['mode'],'dual')
        response=await self.client.post('/api/provider-collaboration',json={'mode':'invalid'},headers={'X-Avatar-Client':'1'})
        self.assertEqual(response.status,400)
        response=await self.client.get('/api/provider')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn('local-test',await response.text())


class RuntimeReload(unittest.TestCase):
    def test_role_reasoning_on_wire_reload_and_model_scope(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(body)
                self.send_response(200)
                if body.get('stream'):
                    self.send_header('Content-Type','text/event-stream');self.end_headers()
                    chunk=dict(id='role-test',object='chat.completion.chunk',created=1,model=body['model'],
                               choices=[dict(index=0,delta={'content':'角色验证成功'},finish_reason='stop')])
                    self.wfile.write(('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode())
                else:
                    self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(json.dumps(dict(id='role-test',object='chat.completion',created=1,model=body['model'],
                        choices=[dict(index=0,message={'role':'assistant','content':'后台验证成功'},finish_reason='stop')])).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        endpoint=f'http://127.0.0.1:{server.server_port}/v1'
        cfg=SimpleNamespace(big_model_engine='deepseek-v4.1-flash',big_model_base_url=endpoint,big_model_api_key='big-test',
            gpt_base_url=endpoint,gpt_model_engine='deepseek-v4.1-flash',key_gpt_api_key='small-test',load_config=lambda:None)
        with tempfile.TemporaryDirectory() as directory:
            config=provider.read_config(Path(directory)/'empty.conf')
            config['llm_generation:small']=dict(base_url=endpoint,model=cfg.gpt_model_engine,thinking='disabled',reasoning_effort='low')
            config['llm_generation:big']=dict(base_url=endpoint,model=cfg.big_model_engine,thinking='enabled',reasoning_effort='medium')
            try:
                with patch.object(provider,'read_config',return_value=config):
                    self.assertEqual(''.join(c.content for c in make_llm(cfg).stream('本地角色验证')),'角色验证成功')
                    self.assertEqual(make_llm(cfg,'big',False).invoke('本地角色验证').content,'后台验证成功')
                    self.assertEqual(calls[0]['thinking'],{'type':'disabled'})
                    self.assertEqual(calls[0]['reasoning_effort'],'low')
                    self.assertEqual(calls[1]['thinking'],{'type':'enabled'})
                    self.assertEqual(calls[1]['reasoning_effort'],'medium')
                    meta=provider.generation_metadata('big',endpoint,cfg.big_model_engine,config)
                    self.assertEqual(meta['effective_reasoning_effort'],'high')
                    config['llm_generation:small']['reasoning_effort']='none'
                    make_llm(cfg,streaming=False).invoke('本地热更新验证')
                    self.assertEqual(calls[2]['reasoning_effort'],'none')
                    cfg.gpt_model_engine='other-model'
                    make_llm(cfg,streaming=False).invoke('模型切换验证')
                    self.assertNotIn('thinking',calls[3])
                    self.assertNotIn('reasoning_effort',calls[3])
                    cfg.gpt_model_engine='deepseek-v4.1-flash'
                    config['llm_generation:small']['base_url']='https://another.example/v1'
                    self.assertEqual(provider.generation_options('small',endpoint,cfg.gpt_model_engine,config),{})
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_real_langchain_sse_uses_new_model_and_key_next_request(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(dict(body=data,authorization=self.headers.get('Authorization'),ua=self.headers.get('User-Agent')))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for text in ('口型','测试'):
                    chunk={'id':'local-probe','object':'chat.completion.chunk','created':1,'model':data['model'],
                           'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        config=SimpleNamespace(big_model_engine='',big_model_base_url='',big_model_api_key='',
            gpt_base_url=f'http://127.0.0.1:{server.server_port}/v1',gpt_model_engine='first-model',key_gpt_api_key='first-test-key',load_config=lambda:None)
        try:
            llm=ReloadableLLM(lambda role,streaming:make_llm(config,role,streaming))
            set_session('Avatar2D','local-conversation')
            self.assertEqual(''.join(c.content for c in llm.stream('你好')),'口型测试')
            config.gpt_model_engine='org/second-model';config.key_gpt_api_key='second-test-key'
            self.assertEqual(''.join(c.content for c in llm.stream('你好')),'口型测试')
            self.assertEqual([c['body']['model'] for c in calls],['first-model','org/second-model'])
            self.assertEqual([c['authorization'] for c in calls],['Bearer first-test-key','Bearer second-test-key'])
            self.assertTrue(all(c['ua']=='Fay-DigitalPresenter/1.0' for c in calls))
            config.gpt_base_url=provider.PRESETS['opencode_go']['base_url']
            first=make_llm(config);second=make_llm(config)
            self.assertEqual(first.default_headers['x-opencode-session'],second.default_headers['x-opencode-session'])
            self.assertNotIn('Avatar2D',first.default_headers['x-opencode-session'])
            config.big_model_engine='background-model'
            config.big_model_base_url=config.gpt_base_url
            config.big_model_api_key='background-test-key'
            big=make_llm(config,'big',False,session_id='local-conversation')
            self.assertEqual(big.model_name,'background-model')
            self.assertEqual(big.openai_api_key.get_secret_value(),'background-test-key')
            self.assertEqual(big.default_headers['x-opencode-session'],first.default_headers['x-opencode-session'])
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main(verbosity=2)
