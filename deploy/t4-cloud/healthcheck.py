"""Local readiness probes; no credentials or public traffic."""
import json,socket,sys,urllib.request
kind=sys.argv[1]
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(url,data=None):
    request=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
    with http.open(request,timeout=5) as response:return json.load(response)
if kind=='presenter':
    health=get('http://127.0.0.1:8766/api/health')
    assert health['model_state']=='ready' and not health['render_error']
elif kind=='asr':assert get('http://127.0.0.1:8780/health')['state']=='ready'
elif kind=='fay':assert get('http://127.0.0.1:5000/api/get-run-status',b'{}')['status']
elif kind=='attendance':assert get('http://127.0.0.1:8783/health')['tool']=='attendance_check_in'
elif kind=='turn':
    with socket.create_connection(('127.0.0.1',3478),timeout=3):pass
else:raise ValueError(kind)
