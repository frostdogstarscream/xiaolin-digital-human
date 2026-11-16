import hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path('D:/XiaolinDigitalHuman');STAGE=ROOT/'deployment/qwen-new-mode-20261110'
source=STAGE/'lossless-patch.zip'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='064b6341e3a649d26413f8d87684ba53b7f8eb75b8ab6778ef47385a29d9dcbd'
with zipfile.ZipFile(source) as z:
    manifest=json.loads(z.read('manifest.json'))
    for name,digest in manifest.items():
        path=(ROOT/name).resolve();assert path.is_relative_to(ROOT)
        data=z.read(name);assert hashlib.sha256(data).hexdigest()==digest
        if path.exists() and path.read_bytes()!=data:
            backup=STAGE/'before-lossless-cache'/name;backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(path,backup)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
(STAGE/'lossless-patch-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
samples=[]
for line in (STAGE/'baseline-mmap-Performance.stdout.log').read_text(encoding='utf-8').splitlines():
    try:record=json.loads(line)
    except json.JSONDecodeError:continue
    if 'seconds' in record and 'total_seconds' in record:samples.append(record)
baseline=dict(status='NOT_PASSED_STOPPED_EARLY',reason='Sustained queue growth and paging on 8GB host; no resolution or precision reduction',samples=samples,
    observed_available_memory_mb=242,observed_page_reads_per_second=3130)
(STAGE/'reports/baseline-mmap.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
print('Verified isolated lossless-cache adaptation installed; original frame arrays retained')
