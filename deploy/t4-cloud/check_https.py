"""Check strict TLS and the authenticated reverse proxy through loopback."""
import asyncio,base64,hashlib,hmac,http.client,json,socket,ssl,time
from pathlib import Path
import aiohttp

HOST='36.133.88.94'
PORT=6443
access=json.loads(Path('/shared/config/web-access.json').read_text())
context=ssl.create_default_context(cafile='/shared/certs/ca.crt')
class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw=socket.create_connection(('127.0.0.1',PORT),timeout=15)
        self.sock=context.wrap_socket(raw,server_hostname=HOST)
auth='Basic '+base64.b64encode((access['username']+':'+access['password']).encode()).decode()
records=[]
def check(path,expected,method='GET',authenticated=True,origin=None):
    connection=LocalHTTPS(HOST,timeout=15)
    headers={'X-Avatar-Client':'1'}
    if authenticated:headers['Authorization']=auth
    if origin:headers['Origin']=origin
    connection.request(method,path,body='{}' if method=='POST' else None,headers=headers)
    response=connection.getresponse();body=response.read()
    records.append(dict(path=path,method=method,status=response.status,expected=expected))
    assert response.status==expected,records[-1]
    connection.close();return body

async def main():
    check('/',401,authenticated=False)
    check('/',200)
    configuration=json.loads(check('/api/rtc-config',200))
    assert len(configuration['iceServers'])==2
    check('/api/rtc-config',401,authenticated=False)
    check('/api/say',410,'POST')
    check('/api/action',410,'POST')
    check('/api/tts/pcm',404,'POST')
    check('/api/interrupt',403,'POST',origin='https://invalid.example')
    # Use wss://127.0.0.1 transport with an explicitly verified public IP identity.
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(f'wss://127.0.0.1:{PORT}/ws',ssl=context,server_hostname=HOST,
                auth=aiohttp.BasicAuth(access['username'],access['password']),headers={'Origin':f'https://{HOST}:{PORT}'}) as ws:
            event=await ws.receive_json(timeout=10)
            assert 'client_id' in event
            records.append(dict(path='/ws',status=101,received_event=event.get('event')))
    from aioice import Connection,TransportPolicy
    secret=Path('/shared/config/turn-secret').read_bytes().strip()
    username=str(int(time.time())+120)+':test'
    password=base64.b64encode(hmac.new(secret,username.encode(),hashlib.sha1).digest()).decode()
    for transport in ('udp','tcp'):
        peer=Connection(ice_controlling=True,turn_server=('127.0.0.1',6478),turn_username=username,
            turn_password=password,turn_transport=transport,transport_policy=TransportPolicy.RELAY)
        try:
            await peer.gather_candidates()
            relay=[c for c in peer.local_candidates if c.type=='relay']
            assert relay and all(10000<=c.port<=10049 for c in relay)
            records.append(dict(turn_transport=transport,allocated=[dict(host=c.host,port=c.port) for c in relay]))
        finally:await peer.close()
    output=dict(status='PASSED',scope='server-local TLS/WSS/TURN allocation; public path not proven',checks=records)
    Path('/app/deployment/https-local-check.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(output))
asyncio.run(main())
