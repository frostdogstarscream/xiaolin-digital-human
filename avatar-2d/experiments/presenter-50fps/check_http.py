import asyncio,json,ssl
from pathlib import Path
import aiohttp
ROOT=Path(__file__).resolve().parents[3];BASE='https://36.133.88.94:6444/experiments/50fps/'
async def main():
    account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text())
    context=ssl.create_default_context(cafile=str(ROOT/'runtime/server-4t4/delivery/xiaolin-root-ca.crt'));rows=[]
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=context),trust_env=False) as http:
        for path,authenticated,expected,headers in [('',False,401,{}),('rtc-config',False,401,{}),('',True,200,{}),('live',True,200,{}),('media/idle-random-50fps.mp4',True,206,{'Range':'bytes=0-63'})]:
            async with http.get(BASE+path,auth=aiohttp.BasicAuth(account['username'],account['password']) if authenticated else None,headers=headers) as response:
                assert response.status==expected,(path,response.status);await response.read();rows.append(dict(path=path,status=response.status))
        async with http.post(BASE+'offer',auth=aiohttp.BasicAuth(account['username'],account['password']),headers={'Origin':'https://invalid.example'},json={}) as response:
            assert response.status==403;rows.append(dict(path='offer',invalid_origin_rejected=True))
    account.clear();report=dict(status='PASSED',strict_tls=True,checks=rows)
    (ROOT/'avatar-2d/outputs/presenter-50fps/http-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
asyncio.run(main())
