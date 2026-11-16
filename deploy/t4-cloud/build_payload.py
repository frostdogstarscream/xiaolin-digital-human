"""Freeze the current application and approved configuration for Linux deployment."""
import configparser
import hashlib
import io
import json
import re
import shutil
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'runtime/server-4t4'
STAGE = WORK / 'release'
STAGE.mkdir(exist_ok=True)
DEPLOY = ROOT / 'deploy/t4-cloud'
selected = {}
native = ROOT / 'fay-ue4/runtime/fay-local/app'
excluded_dirs = {'__pycache__', '.git', '.vscode', 'memory', 'samples', 'logs', 'cache_data',
                 'fay_player_knowledge', 'readme', 'docs', 'test', 'node_modules'}
excluded_files = {'system.conf', 'system.conf.bak', 'config.json', 'verifier.json', 'qa.csv', '.env', '.env.local'}


def select_tree(relative):
    base = ROOT / relative
    for path in base.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(p in excluded_dirs for p in rel.parts) or path.name in excluded_files:
            continue
        if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pyc', '.log', '.bak', '.exe', '.dll'}:
            continue
        if '/faymcp/data/' in rel.as_posix():
            continue
        selected[rel.as_posix()] = path


for directory in ('avatar-2d/service', 'avatar-2d/tools', 'avatar-2d/web', 'avatar-2d/tests',
                  'avatar-2d/vendor', 'fay-ue4/runtime/fay-local/app'):
    select_tree(directory)
for name in ('fay-ue4/tools/run_fay_local.py', 'attendance-mcp/server.py', 'attendance-mcp/manage.py',
             'attendance-mcp/check_protocol.py', 'avatar-2d/assets/presenter-v1/motions-v1/action-library.json',
             'avatar-2d/assets/calibration-speech-16k-v1.wav'):
    selected[name] = ROOT / name
for name, path in selected.items():
    destination = STAGE / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def change(relative, before, after):
    path = STAGE / relative
    text = path.read_text(encoding='utf-8-sig')
    if text.count(before) != 1:
        raise RuntimeError('Unexpected source anchor in ' + relative)
    path.write_text(text.replace(before, after), encoding='utf-8')


engine = STAGE / 'avatar-2d/service/live_engine.py'
baseline = json.loads((ROOT / 'runtime/deploy-1660/pcm-reset-patch.json').read_text())
if hashlib.sha256(engine.read_bytes()).hexdigest() != baseline['source_sha256']:
    raise RuntimeError('Renderer changed since verified PCM fix; review is required')
shutil.copyfile(ROOT / 'runtime/deploy-1660/live_engine.memory.target.py', engine)
fixture = 'avatar-2d/tests/check_automatic_gestures.py'
change(fixture, 'p=SimpleNamespace(generation=1,lock=threading.Lock(),reset_requested=threading.Event(),',
       'p=SimpleNamespace(generation=1,lock=threading.Lock(),reset_requested=threading.Event(),pending_audio=[],')
shutil.copyfile(ROOT / 'runtime/deploy-1660/check-reset-pcm.py', STAGE / 'avatar-2d/tests/check_reset_pcm.py')
shutil.copyfile(DEPLOY / 'cloud_runtime.py', STAGE / 'avatar-2d/service/cloud_runtime.py')

app = 'avatar-2d/service/app.py'
change(app, 'import provider_config', 'import provider_config\nfrom cloud_runtime import allowed_origins')
path = STAGE / app
text = path.read_text(encoding='utf-8')
text = text.replace("(f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}')", 'allowed_origins(PORT)')
path.write_text(text, encoding='utf-8')
change('avatar-2d/service/provider_config.py', "path = Path(path or FAY/'system.conf')",
       "path = Path(path or FAY/'system.conf').resolve()")
for relative in ('avatar-2d/service/bailian_speech.py', 'avatar-2d/service/local_asr_server.py',
                 'avatar-2d/service/renderer.py'):
    path = STAGE / relative
    text = path.read_text(encoding='utf-8-sig')
    text, count = re.subn(r"FFMPEG\s*=.*ffmpeg\.exe'", 'from cloud_runtime import ffmpeg_path\nFFMPEG=ffmpeg_path(ROOT)', text)
    if count != 1:
        raise RuntimeError('Missing FFmpeg anchor in ' + relative)
    path.write_text(text, encoding='utf-8')
live = 'avatar-2d/service/live_app.py'
change(live, 'import app as legacy', 'import app as legacy\nfrom cloud_runtime import configure_rtc, ice_servers, ffmpeg_path')
change(live, '            self.rtc = RTCManager(options())', '            configure_rtc()\n            self.rtc = RTCManager(options())')
change(live, "ffmpeg = ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'", 'ffmpeg = ffmpeg_path(ROOT)')
change(live, '    async def index(request):', "    async def rtc_config(request):\n        return web.json_response({'iceServers': ice_servers()}, headers={'Cache-Control':'no-store'})\n    async def index(request):")
change(live, "    application.add_routes([web.get('/', index),", "    application.add_routes([web.get('/api/rtc-config', rtc_config), web.get('/', index),")
change('avatar-2d/web/live.js', '  const connection=new RTCPeerConnection({iceServers:[]});pc=connection;',
       "  let rtcConfig;\n  try{\n    const rtcResponse=await fetch('/api/rtc-config');\n    if(!rtcResponse.ok)throw Error('音视频配置读取失败');\n    rtcConfig=await rtcResponse.json();\n  }catch(error){connecting=false;message(error.message,true);retryDisplay();return false;}\n  const connection=new RTCPeerConnection(rtcConfig);pc=connection;")
change('avatar-2d/web/live.js', "new WebSocket('ws://'+location.host+'/ws')",
       "new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws')")
change('avatar-2d/web/live.js', '数字人已连接，可以直接录音、问答或播报。', '数字人已连接，可以直接录音或输入问题。')
change('avatar-2d/web/live.html', '录音仅发送到本机 FunASR。', '录音发送到本服务器的 FunASR。')
page = STAGE / 'avatar-2d/web/live.html'
markup = page.read_text(encoding='utf-8')
markup, count = re.subn(r'<a[^>]*href="http://127\.0\.0\.1:5000/setting"[^>]*>.*?</a>',
    '<p class="small">Fay 人设与服务设置通过维护端访问。</p>', markup)
if count != 1:
    raise RuntimeError('Missing cloud maintenance-link anchor')
page.write_text(markup.replace('<head>', '<head><link rel="icon" href="data:,">'), encoding='utf-8')

manifest = json.loads((ROOT / 'avatar-2d/source-manifest.json').read_text(encoding='utf-8-sig'))
manifest['source_directory'] = '/app/avatar-2d/vendor/LiveTalking-' + manifest['commit']
(STAGE / 'avatar-2d/source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
deployment = STAGE / 'deployment'
deployment.mkdir(exist_ok=True)
for name in ('bootstrap.py', 'healthcheck.py', 'check_https.py', 'check_reconnect.py', 'nginx.conf', 'compose.yaml', 'ports.json'):
    shutil.copyfile(DEPLOY / name, deployment / name)

for environment, source in [('presenter', 'presenter'), ('asr', 'asr'), ('fay', 'fay')]:
    lines = (ROOT / 'runtime/deploy-1660' / (source + '.requirements.txt')).read_text().splitlines()
    skip = {'torch', 'torchaudio', 'torchvision', 'pywin32'}
    filtered = [line for line in lines if line.split('==')[0].lower() not in skip]
    (WORK / f'requirements-{environment}.txt').write_text('\n'.join(filtered) + '\n', encoding='utf-8')
shutil.copyfile(DEPLOY / 'Dockerfile', WORK / 'Dockerfile')

config = configparser.ConfigParser(interpolation=None)
config.read(native / 'system.conf', encoding='utf-8-sig')
allowed = {('key', 'gpt_api_key'), ('key', 'big_model_api_key'), ('key', 'embedding_api_key'),
           ('key', 'rerank_api_key'), ('key', 'bailian_tts_api_key'), ('llm_profile:opencode_go', 'api_key')}
for section in config.sections():
    for field in config[section]:
        if any(word in field.lower() for word in ('api_key', 'secret', 'password', 'access_token', 'key_id', 'app_key', 'credential')):
            if (section, field) not in allowed:
                config[section][field] = ''
private = WORK / 'private'
private.mkdir(exist_ok=True)
with (private / 'system.conf').open('w', encoding='utf-8') as stream:
    config.write(stream)
settings = json.loads((native / 'config.json').read_text(encoding='utf-8-sig'))
settings['source']['record']['enabled'] = False
settings['source']['automatic_player_status'] = False
settings['interact']['playSound'] = False
(private / 'config.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')

records = []
with tarfile.open(WORK / 'application.tar.gz', 'w:gz', compresslevel=1) as archive:
    for path in sorted(STAGE.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        name = path.relative_to(STAGE).as_posix()
        archive.add(path, arcname=name, recursive=False)
        records.append(dict(path=name, size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
(WORK / 'application-manifest.json').write_text(json.dumps({'files': records}, indent=2), encoding='utf-8')
assets = {}
for folder in ('avatar-2d/models/SenseVoiceSmall', 'avatar-2d/runtime/avatars'):
    for path in (ROOT / folder).rglob('*'):
        if path.is_file() and '.git' not in path.parts and '__pycache__' not in path.parts:
            assets[path.relative_to(ROOT).as_posix()] = path
assets['avatar-2d/models/wav2lip256.pth'] = ROOT / 'avatar-2d/models/wav2lip256.pth'
asset_records = []
with tarfile.open(WORK / 'assets.tar', 'w') as archive:
    for name, path in sorted(assets.items()):
        archive.add(path, arcname=name, recursive=False)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        asset_records.append(dict(path=name, size=path.stat().st_size, sha256=digest))
(WORK / 'asset-manifest.json').write_text(json.dumps({'files': asset_records}, indent=2), encoding='utf-8')
print(json.dumps({'application_files': len(records), 'asset_files': len(asset_records),
    'asset_bytes': (WORK / 'assets.tar').stat().st_size, 'approved_credential_fields': len(allowed)}))
