"""Patch only the isolated evaluation copy, preserving original source backups."""
from pathlib import Path
import shutil

root=Path('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval')
path=root/'service/engine.py'
backup=path.with_suffix('.py.original')
if not backup.exists():shutil.copy2(path,backup)
s=backup.read_text()
old="if backend=='musetalk':assets=MuseAssets()"
assert old in s
s=s.replace(old,"if backend=='musetalk':\n        assets=MuseAssets()\n        from decoder_variants import configure\n        configure(assets,ROOT)\n        with torch.inference_mode():assets.predict([('welcome-wave',0)]*4,np.ones((4,50,384),np.float32))")
path.write_text(s)
path=root/'service/server.py'
backup=path.with_suffix('.py.original')
if not backup.exists():shutil.copy2(path,backup)
s=backup.read_text()
old="'production_mutations':False,'cloud_calls':0"
assert old in s
s=s.replace(old,"'decoder_variant':getattr(self.assets,'decoder_variant','original'),'production_mutations':False,'cloud_calls':0")
path.write_text(s)
path=root/'tests/check_realtime.py'
backup=path.with_suffix('.py.original')
if not backup.exists():shutil.copy2(path,backup)
s=backup.read_text()
s=s.replace("result={'backend':backend,'model_load_seconds':h['load_seconds'],'latency_samples':[]}",
            "result={'backend':backend,'decoder_variant':h.get('decoder_variant','original'),'model_load_seconds':h['load_seconds'],'latency_samples':[]}")
s=s.replace("report['results']=report['results'][:1]", "report['results']=report['results'][:1]\n        report['baseline_reused_from']='run02-baseline.json'")
path.write_text(s)
print('ISOLATED_VARIANTS_ENABLED')
