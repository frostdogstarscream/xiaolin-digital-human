"""Backup memory locally, then re-embed existing content with the selected paid model."""
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
import provider_config as provider


def main():
    cfg=provider.read_config()['key']
    assert cfg['embedding_api_model']=='Pro/BAAI/bge-m3'
    base=provider.FAY/'memory'
    assert base.resolve().is_relative_to(ROOT.parent.resolve())
    backup=ROOT/'runtime/memory-model-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True)
    shutil.copytree(base,backup/'memory')
    report=dict(model=cfg['embedding_api_model'],backup=str(backup),users=[],node_contents_preserved=True,using_mock_vectors=False)
    http=requests.Session();http.trust_env=False
    for nodes_path in base.rglob('nodes.json'):
        nodes=json.loads(nodes_path.read_text(encoding='utf-8-sig'))
        embeddings_path=nodes_path.with_name('embeddings.json')
        previous=json.loads(embeddings_path.read_text(encoding='utf-8-sig')) if embeddings_path.exists() else {}
        texts=list(dict.fromkeys([n['content'] for n in nodes]+list(previous)))
        if not texts:continue
        node_hash=hashlib.sha256(nodes_path.read_bytes()).hexdigest()
        rebuilt={}
        for start in range(0,len(texts),8):
            batch=texts[start:start+8]
            response=http.post(cfg['embedding_base_url'].rstrip('/')+'/embeddings',
                headers={'Authorization':'Bearer '+cfg['embedding_api_key']},
                json={'model':cfg['embedding_api_model'],'input':batch},timeout=(5,15),allow_redirects=False)
            if response.status_code!=200:raise RuntimeError('Paid embedding migration HTTP '+str(response.status_code))
            rows=sorted(response.json()['data'],key=lambda item:item['index'])
            assert len(rows)==len(batch)
            for text,row in zip(batch,rows):
                vector=row['embedding']
                assert len(vector)==1024 and all(math.isfinite(v) for v in vector) and any(vector)
                rebuilt[text]=vector
        temporary=embeddings_path.with_suffix('.migrate.tmp')
        temporary.write_text(json.dumps(rebuilt,ensure_ascii=False),encoding='utf-8');temporary.replace(embeddings_path)
        assert hashlib.sha256(nodes_path.read_bytes()).hexdigest()==node_hash
        report['users'].append(dict(user_directory=str(nodes_path.parent.parent.relative_to(base)),nodes=len(nodes),vectors=len(rebuilt),dimensions=1024,nodes_sha256=node_hash))
    output=ROOT/'docs/memory-embedding-migration-2026-11-04.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
