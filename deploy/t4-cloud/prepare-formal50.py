"""Create a separate 50 fps formal candidate from the frozen current gateway."""
import datetime,json,shutil,subprocess
from pathlib import Path
base=Path('/opt/xiaolin');old=base/'evaluations/presenter-v2-1080/avatar-2d'
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');release=base/'releases'/('formal50-'+stamp);root=release/'avatar-2d';root.mkdir(parents=True)
for name in ('qwen-realtime-v2','presenter-v2-1080','presenter-50fps'):
 shutil.copytree(old/'experiments'/name,root/'experiments'/name,ignore=shutil.ignore_patterns('__pycache__','*.before-*'))
for name in ('assets','runtime','models','tools','outputs'):(root/name).symlink_to('/eval/avatar-2d/'+name,target_is_directory=True)
(root/'service').symlink_to('/app/avatar-2d/service',target_is_directory=True)
shutil.copy2(old/'source-manifest.json',root/'source-manifest.json')
state=release/'state';state.mkdir(mode=0o700)
settings=json.loads((old/'runtime/qwen-realtime-v2/settings.json').read_text());settings['lipsync_backend']='wav2lip';settings['revision']+=1
(state/'settings.json').write_text(json.dumps(settings,indent=2))
(state/'capabilities.sqlite3').symlink_to('/eval/avatar-2d/runtime/qwen-realtime-v2/capabilities.sqlite3')
# The video cadence is configured only after the previous media session is closed.
p=root/'experiments/presenter-50fps/engine50.py';s=p.read_text().replace('webrtc.VIDEO_PTIME=.02','');p.write_text(s)
p=root/'experiments/qwen-realtime-v2/gateway_musetalk.py';s=p.read_text()
s=s.replace("sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))", "sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))\nsys.path.insert(0,str(HERE.parent/'presenter-50fps'))")
s=s.replace("self.assets=await asyncio.to_thread(self.engine.Assets)", "self.assets=await asyncio.to_thread(self.engine.Assets);self.configure_video(self.settings.value['lipsync_backend'])")
s=s.replace("return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'live_engine_v2')", "return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'engine50')")
marker='    async def settings_api(self,request):'
s=s.replace(marker,"""    @staticmethod
    def configure_video(backend):
        from server import webrtc
        if backend=='wav2lip':
            from encoder50 import configure
            webrtc.VIDEO_PTIME=.02
        else:
            from video_encoder import configure
            webrtc.VIDEO_PTIME=.04
        configure()
"""+marker)
s=s.replace('                        if self.owner is owner:self.owner=None\n        return web.json_response', "                        if self.owner is owner:self.owner=None\n                if changed:self.configure_video(data['lipsync_backend'])\n        return web.json_response")
s=s.replace("profile='presenter-v2-1080',", "profile='presenter-formal-50fps',video_fps=50 if self.settings.value['lipsync_backend']=='wav2lip' else 25,")
(root/'experiments/qwen-realtime-v2/gateway50.py').write_text(s)
p=root/'experiments/qwen-realtime-v2/index.html';s=p.read_text().replace('实时语音 · 1080p · 模型自动协调','实时语音 · 1080p / 50 fps · 模型自动协调').replace('Wav2Lip（响应更快）','Wav2Lip FP16（50 fps）').replace('MuseTalk 1.5（原版，T4 上播放较慢）','MuseTalk 1.5（25 fps，T4 上播放较慢）');p.write_text(s)
p=root/'experiments/qwen-realtime-v2/demo.js';s=p.read_text().replace('1080p · 音视频已连接','1080p · 音视频已连接');p.write_text(s)
def run(*args):return subprocess.check_output(args,text=True).strip()
info=json.loads(run('docker','inspect','xiaolin-qwen-musetalk-v2'))[0]
args=['docker','run','-d','--name','xiaolin-formal-50fps','--restart','no','--network','host','--device','nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44','--shm-size','2g']
for val in info['Config']['Env']:
 if val.startswith('QWEN_DEMO_PORT='):continue
 if val.startswith('XIAOLIN_ICE_MIN_PORT=') or val.startswith('XIAOLIN_ICE_MAX_PORT='):continue
 if val.startswith('QWEN_STATE_DIR='):continue
 args+=['-e',val]
for val in ['QWEN_DEMO_PORT=8773','QWEN_STATE_DIR=/formal/state','XIAOLIN_50_PRECISION=fp16','XIAOLIN_ICE_MIN_PORT=10300','XIAOLIN_ICE_MAX_PORT=10349','OPENBLAS_NUM_THREADS=1','MKL_NUM_THREADS=1','CUDNN_CONV_WSCAP_DBG=256']:args+=['-e',val]
for m in info['Mounts']:args+=['-v',m['Source']+':'+m['Destination']+('' if m['RW'] else ':ro')]
args+=['-v',str(release)+':/formal','-w','/formal/avatar-2d',info['Config']['Image'],'python','/formal/avatar-2d/experiments/qwen-realtime-v2/gateway50.py']
print('CANDIDATE',run(*args))
report={'release':str(release),'container':'xiaolin-formal-50fps','candidate_port':8773,'fps':50,'lipsync_backend':'wav2lip','precision':'fp16','baseline':json.loads((base/'deployment/formal25-baseline.json').read_text())['baseline']}
(base/'deployment/formal50-candidate.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
