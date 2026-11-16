"""Acquire a pinned official SenseVoice snapshot without executing remote code."""
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3847d57b6bdf2dd8875cb1508d2af43d80a16bf7'
REPO = 'FunAudioLLM/SenseVoiceSmall'
FILES = ['config.yaml', 'configuration.json', 'am.mvn',
         'chn_jpn_yue_eng_ko_spectok.bpe.model', 'model.pt', 'README.md']


def main():
    target = ROOT/'models/SenseVoiceSmall'
    target.mkdir(parents=True, exist_ok=True)
    info = requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=30)
    info.raise_for_status()
    metadata = {x['rfilename']:x for x in info.json()['siblings']}
    records = []
    for name in FILES:
        path = target/name
        expected = metadata[name].get('lfs', {}).get('sha256')
        if not path.exists() or (expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected):
            partial = path.with_suffix(path.suffix+'.part')
            with requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}', stream=True, timeout=(15,90)) as response:
                response.raise_for_status()
                with partial.open('wb') as out:
                    for chunk in response.iter_content(1024*1024):
                        out.write(chunk)
            digest = hashlib.file_digest(partial.open('rb'), 'sha256').hexdigest()
            if expected and expected!=digest:
                raise RuntimeError('Model checksum mismatch: '+name)
            partial.replace(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        records.append(dict(file=name, bytes=path.stat().st_size, sha256=digest, expected_sha256=expected))
        print('Verified',name,path.stat().st_size,flush=True)
    (target/'download-manifest.json').write_text(json.dumps(dict(repo=REPO,revision=REVISION,files=records),indent=2),encoding='utf-8')


if __name__=='__main__':main()
