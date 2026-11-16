from pathlib import Path
import shutil
folder=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2')
p=folder/'demo.js';shutil.copy2(p,p.with_suffix('.js.before-firefox-bundle'))
s=p.read_text();assert "bundlePolicy:'max-bundle'," in s
p.write_text(s.replace("bundlePolicy:'max-bundle',",''))
p=folder/'index.html';shutil.copy2(p,p.with_suffix('.html.before-firefox-bundle'))
s=p.read_text().replace('/demo.js?v=20261110-wake1','/demo.js?v=20261111-firefox-bundle1');p.write_text(s)
print('BUNDLE_POLICY_MATCHES_6443')
