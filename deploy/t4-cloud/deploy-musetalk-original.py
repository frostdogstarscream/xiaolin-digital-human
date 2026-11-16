import json,shutil,subprocess,time
from pathlib import Path

def run(*args):return subprocess.check_output(args,text=True).strip()
source=Path('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval')
root=Path('/opt/xiaolin/musetalk/20261111-original')
assert not root.exists(), 'Deployment already exists'
root.mkdir(parents=True)
for name in ('service','web','fixtures','docs','tests'):
    shutil.copytree(source/name,root/name,ignore=shutil.ignore_patterns('__pycache__'))
for name in ('models','cache'):(root/name).symlink_to(source/name,target_is_directory=True)
(root/'outputs').mkdir()
s=(root/'service/server.py').read_text()
s=s.replace("self.switch('wav2lip')","self.switch('musetalk')")
s=s.replace("'http://localhost:8768')","'http://localhost:8768','https://36.133.88.94:6445')")
s=s.replace('port=8768,access_log=None','port=8789,access_log=None')
s=s.replace("    evaluation=Evaluation();", "    from cloud_runtime import configure_rtc\n    configure_rtc()\n    evaluation=Evaluation();")
s=s.replace("    app.add_routes([", "    async def ice(request):\n        from cloud_runtime import ice_servers\n        return web.json_response({'iceServers':ice_servers()})\n    app.router.add_get('/api/ice',ice)\n    app.add_routes([")
(root/'service/server.py').write_text(s)
p=root/'web/client.js'
s=p.read_text().replace("new RTCPeerConnection({iceServers:[]})", "new RTCPeerConnection(await (await fetch('/api/ice')).json())")
s=s.replace("?'MuseTalk 1.5':'Wav2Lip'", "?'MuseTalk 1.5 · 原版 VAE':'Wav2Lip'")
p.write_text(s)
info=json.loads(run('docker','inspect','xiaolin-presenter-1'))[0]
env=dict(x.split('=',1) for x in info['Config']['Env'])
args=['docker','run','-d','--name','xiaolin-musetalk-original','--restart','unless-stopped','--network','host','--device','nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44','--shm-size','2g','--cpus','8','--memory','24g']
for k,v in env.items():
    if k.startswith('XIAOLIN_TURN_') or k=='XIAOLIN_BIND_IP':args+=['-e',k+'='+v]
for x in ['XIAOLIN_TURN_SECRET_FILE=/config/turn-secret','MUSE_DECODER_VARIANT=original','OMP_NUM_THREADS=4','HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','SDL_AUDIODRIVER=dummy','XIAOLIN_ICE_MIN_PORT=10080','XIAOLIN_ICE_MAX_PORT=10099']:args+=['-e',x]
for x in ['/opt/xiaolin/releases/20261110-ports:/app:ro','/opt/xiaolin/shared/assets:/shared/assets:ro','/opt/xiaolin/shared/assets/avatar-2d/runtime/avatars:/shared/data/presenter-runtime/avatars:ro','/opt/xiaolin/shared/config:/config:ro',str(source)+':'+str(source)+':ro',str(root)+':/eval']:args+=['-v',x]
args+=['-w','/eval','xiaolin-presenter:20261110-ports','python','service/server.py']
print('MODEL_CONTAINER',run(*args))
conf='''events {}
http {
 server {
 listen 6445 ssl;
 server_name 36.133.88.94;
 ssl_certificate /certs/server.crt;
 ssl_certificate_key /certs/server.key;
 ssl_protocols TLSv1.2 TLSv1.3;
 auth_basic "Xiaolin MuseTalk";
 auth_basic_user_file /config/access.htpasswd;
 client_max_body_size 1m;
 location / { proxy_pass http://127.0.0.1:8789; proxy_set_header Host $http_host; proxy_set_header Origin $http_origin; proxy_read_timeout 3600s; proxy_buffering off; }
 }
}
'''
(root/'nginx.conf').write_text(conf)
print('HTTPS_CONTAINER',run('docker','run','-d','--name','xiaolin-musetalk-https','--restart','unless-stopped','--network','host','-v',str(root/'nginx.conf')+':/etc/nginx/nginx.conf:ro','-v','/opt/xiaolin/shared/config:/config:ro','-v','/opt/xiaolin/shared/certs:/certs:ro','nginx:1.28-alpine'))
(root/'deployment.json').write_text(json.dumps({'model':'MuseTalk 1.5','decoder':'original','url':'https://36.133.88.94:6445/','scope':'fixed audio and motion preview','source':str(source)},indent=2))
print('DEPLOYED')

