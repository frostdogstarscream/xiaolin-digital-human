import asyncio,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from capabilities import Settings,Store,Router,DEFAULT

class Response:
    status=200
    def __init__(self,value,on_read=None):self.value=value;self.on_read=on_read
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def raise_for_status(self):pass
    async def json(self):
        if self.on_read:self.on_read()
        return self.value
class HTTP:
    def __init__(self):self.get_count=0;self.on_read=None
    def get(self,*args,**kwargs):
        self.get_count+=1
        return Response(dict(tools=[dict(name='attendance_check_in',enabled=True,available=True,server_id=1)]),self.on_read)

class Capabilities(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.settings=Settings(Path(self.temp.name));self.http=HTTP();self.router=Router(self.settings,self.http)
        self.turn=dict(id='turn-one',user='user-a',revision=1,cancelled=False,text='我喜欢喝龙井茶')
    def tearDown(self):self.temp.cleanup()
    def update(self,**values):self.settings.update({**{k:v for k,v in self.settings.public().items() if k!='revision'},**values})
    async def test_settings_persist_validate_boolean_and_revision(self):
        self.update(memory_enabled=False);self.assertEqual(Settings(Path(self.temp.name)).public()['memory_enabled'],False)
        self.assertEqual(self.settings.value['revision'],2)
        with self.assertRaises(ValueError):self.update(mcp_enabled='false')
        self.assertEqual(self.settings.value['revision'],2)
    async def test_disabled_never_calls_provider_or_tool(self):
        self.update(coordinator_enabled=False);self.turn['revision']=2
        self.assertEqual((await self.router.attendance(self.turn))['status'],'disabled')
        self.assertEqual((await self.router.search('memory','query','user-a',self.turn))['status'],'disabled')
        self.assertEqual(self.http.get_count,0)
    async def test_attendance_at_most_once_under_duplicate_calls(self):
        count=0
        async def post(*args,**kwargs):
            nonlocal count
            count+=1;await asyncio.sleep(.02);return dict(success=True,result=dict(content=[dict(type='text',text='success')],isError=False))
        self.router.post=post
        first,second=await asyncio.gather(self.router.attendance(self.turn),self.router.attendance(self.turn))
        self.assertTrue(first['ok']);self.assertFalse(second['ok']);self.assertEqual(count,1)
        again=await self.router.attendance(self.turn);self.assertTrue(again['ok']);self.assertEqual(count,1)
        self.assertTrue(Store(self.router.store.path).claim(self.turn['id'],'attendance_check_in')['ok'])
    async def test_switch_off_before_mcp_dispatch_prevents_call(self):
        self.http.on_read=lambda:self.update(mcp_enabled=False)
        async def post(*args,**kwargs):raise AssertionError('Tool dispatched after disabling')
        self.router.post=post
        self.assertEqual((await self.router.attendance(self.turn))['status'],'disabled')
    async def test_failure_is_not_retried_or_reported_success(self):
        count=0
        async def fail(*args,**kwargs):
            nonlocal count
            count+=1;raise RuntimeError('offline')
        self.router.post=fail
        for _ in range(2):self.assertFalse((await self.router.attendance(self.turn))['ok'])
        self.assertEqual(count,1)
    async def test_scoped_empty_retrieval_never_embeds(self):
        self.router.store.put('knowledge','user-a','a','secret a','Pro/test',[1,0])
        async def embed(*args):raise AssertionError('Unexpected embedding')
        self.router.embed=embed
        self.assertEqual((await self.router.search('knowledge','x','user-b',self.turn))['status'],'empty')
    async def test_real_vector_contract_and_rerank_order(self):
        self.router.store.put('knowledge','user-a','first','source one','Pro/test',[1,0])
        self.router.store.put('knowledge','user-a','second','source two','Pro/test',[1,0])
        async def embed(query):return 'Pro/test',[1,0]
        async def post(url,body,key):
            self.assertTrue(url.endswith('/rerank'));self.assertEqual(body['model'],'Pro/rerank')
            return dict(results=[dict(index=1,relevance_score=.99),dict(index=0,relevance_score=.8)])
        self.router.embed=embed;self.router.post=post
        cfg=dict(rerank_base_url='https://configured.example/v1',rerank_api_key='not-a-secret',rerank_api_model='Pro/rerank')
        with patch('capabilities.credentials',return_value=cfg):
            value=await self.router.search('knowledge','x','user-a',self.turn)
        self.assertEqual(value['rerank_calls'],1);self.assertEqual(value['matches'][0]['title'],'first')
    async def test_cancelled_memory_does_not_write_and_completed_turn_dedupes(self):
        async def embed(text):return 'Pro/test',[1,0]
        self.router.embed=embed;self.turn['cancelled']=True
        await self.router.remember(self.turn,'好的');self.assertEqual(self.router.store.rows('memory','user-a'),[])
        self.turn['cancelled']=False
        await self.router.remember(self.turn,'记住了');await self.router.remember(self.turn,'记住了')
        self.assertEqual(len(Store(self.router.store.path).rows('memory','user-a')),1)
    async def test_index_failure_exposes_no_partial_document(self):
        count=0
        async def embed(text):
            nonlocal count
            count+=1
            if count==2:raise RuntimeError('embedding failed')
            return 'Pro/test',[1,0]
        self.router.embed=embed
        with self.assertRaises(RuntimeError):await self.router.add_knowledge('user-a','test','a'*900)
        self.assertEqual(self.router.store.rows('knowledge','user-a'),[])
    async def test_stale_turn_and_invalid_plan_cannot_execute(self):
        self.update(memory_enabled=False)
        result=await self.router.coordinate(self.turn,dict(attendance='check_in',knowledge_query='',memory_query='',gesture='idle'),lambda _:self.fail('Unexpected gesture'))
        self.assertFalse(result['coordinated']);self.assertEqual(self.http.get_count,0)
        with self.assertRaises(ValueError):await self.router.coordinate(self.turn,dict(attendance='check_in'),lambda _:None)
    async def test_failed_attendance_does_not_nod_as_success(self):
        self.update(mcp_enabled=False);self.turn['revision']=2;selected=[]
        result=await self.router.coordinate(self.turn,dict(attendance='check_in',knowledge_query='',memory_query='',gesture='acknowledge-nod'),lambda value:selected.append(value) or value)
        self.assertEqual(result['attendance']['status'],'disabled');self.assertEqual(selected,['idle'])
    async def test_index_disable_midflight_has_no_partial_commit(self):
        async def embed(text):self.update(knowledge_enabled=False);return 'Pro/test',[1,0]
        self.router.embed=embed
        with self.assertRaises(ValueError):await self.router.add_knowledge('user-a','test','a'*100)
        self.assertEqual(self.router.store.rows('knowledge','user-a'),[])

if __name__=='__main__':unittest.main(verbosity=2)
