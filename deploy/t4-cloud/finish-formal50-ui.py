from pathlib import Path
p=Path('/opt/xiaolin/releases/formal50-20261111-161638/avatar-2d/experiments/qwen-realtime-v2/demo.js')
s=p.read_text()
s=s.replace("$('#lipsync-choice').value=config.lipsync_backend||'wav2lip';","$('#lipsync-choice').value=config.lipsync_backend||'wav2lip';$('#current-fps').textContent=config.lipsync_backend==='wav2lip'?'50 fps':'25 fps';")
p.write_text(s)
p=p.with_name('index.html');s=p.read_text().replace('<title>小霖 · 实时语音新模式</title>','<title>小霖 · 50 fps 正式版</title>').replace('实时语音 · 1080p / 50 fps · 模型自动协调','实时语音 · 1080p / <span id="current-fps">50 fps</span> · 模型自动协调').replace('/demo.js?v=20261111-firefox-turn4','/demo.js?v=20261111-formal50-1');p.write_text(s)
print('DYNAMIC_FPS_LABEL_READY')

