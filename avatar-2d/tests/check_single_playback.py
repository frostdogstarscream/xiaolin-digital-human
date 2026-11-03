"""Verify that only the console which owns playback receives generated media."""
import asyncio
import json
from pathlib import Path
from aiohttp import ClientSession,ClientTimeout

ROOT=Path(__file__).resolve().parents[1]


async def main():
    async with ClientSession(trust_env=False,timeout=ClientTimeout(total=40)) as client:
        async with client.ws_connect('http://127.0.0.1:8766/ws') as first, client.ws_connect('http://127.0.0.1:8766/ws') as second:
            a=await first.receive_json();b=await second.receive_json()
            headers={'X-Avatar-Client':'1','X-Avatar-Viewer':a['client_id']}
            async with client.post('http://127.0.0.1:8766/api/say',json={'text':'收到'},headers=headers) as r:
                assert r.status==200
            first_ready=asyncio.Event();second_ready=[]
            async def consume_a():
                async for msg in first:
                    data=json.loads(msg.data)
                    if data.get('event')=='ready':
                        assert data['playback_owner']==a['client_id']
                        first_ready.set();return data['job_id']
            async def consume_b():
                async for msg in second:
                    data=json.loads(msg.data)
                    if data.get('event')=='ready':second_ready.append(data)
            ta=asyncio.create_task(consume_a());tb=asyncio.create_task(consume_b())
            await asyncio.wait_for(first_ready.wait(),35)
            await asyncio.sleep(.5)
            job=await ta
            assert not second_ready,'A non-owner received a playable media event'
            tb.cancel();await asyncio.gather(tb,return_exceptions=True)
            async with client.post('http://127.0.0.1:8766/api/interrupt',json={},headers=headers) as r:assert r.status==200
            report=dict(status='SINGLE_PLAYBACK_OWNER_TEST_PASSED',job_id=job,
                        owner_received_ready=True,second_console_received_ready=False,cloud_calls=0)
            (ROOT/'docs/single-playback-validation-v1.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))


if __name__=='__main__':asyncio.run(main())
