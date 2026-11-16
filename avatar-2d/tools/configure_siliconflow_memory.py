"""Probe paid retrieval models before saving isolated credentials; enable is a later step."""
import getpass
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
import provider_config as provider

BASE='https://api.siliconflow.cn/v1'
EMBED='Pro/BAAI/bge-m3'
RERANK='Pro/BAAI/bge-reranker-v2-m3'
DOCUMENTS=['参观者希望讲解简洁，每次回答控制在两句话。','展馆停车场位于西侧入口。','今天餐厅提供面条和米饭。']
QUERY='这位参观者喜欢怎样的讲解方式？'


def main():
    print('Waiting for supplied SiliconFlow credential; input is not echoed.',flush=True)
    secret=(getpass.getpass('API Key (hidden): ') if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not secret:raise ValueError('Missing credential')
    before=provider.read_config()
    session=requests.Session();session.trust_env=False
    headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'}
    report=dict(provider='SiliconFlow',base_url=BASE,embedding_model=EMBED,rerank_model=RERANK,
                paid_only=True,saved=False,memory_enabled=False,probes=[])
    for route,body in [('embeddings',dict(model=EMBED,input=DOCUMENTS)),
                       ('rerank',dict(model=RERANK,query=QUERY,documents=DOCUMENTS,top_n=3,return_documents=False))]:
        started=time.perf_counter()
        response=session.post(BASE+'/'+route,headers=headers,json=body,timeout=(8,15),allow_redirects=False)
        item=dict(route=route,http_status=response.status_code,seconds=round(time.perf_counter()-started,4))
        report['probes'].append(item)
        if response.status_code!=200:
            raise RuntimeError('Paid model probe rejected: '+route+' HTTP '+str(response.status_code))
        data=response.json()
        if route=='embeddings':
            vectors=[x['embedding'] for x in data['data']]
            assert len(vectors)==3 and all(len(v)==1024 and all(math.isfinite(x) for x in v) for v in vectors)
            item.update(vectors=3,dimensions=1024,nonzero=all(any(x!=0 for x in v) for v in vectors))
        else:
            assert data['results'][0]['index']==0,'Relevant preference did not rank first'
            item.update(relevant_document_rank=1,score=data['results'][0]['relevance_score'])
    with provider.LOCK:
        config=provider.read_config()
        unchanged_before={s:dict(config[s]) for s in config.sections()}
        config['key'].update(embedding_api_model=EMBED,embedding_base_url=BASE,embedding_api_key=secret,
            embedding_require_real='true',embedding_timeout='8',
            rerank_api_model=RERANK,rerank_base_url=BASE,rerank_api_key=secret,rerank_enabled='true',
            rerank_timeout='8',rerank_candidate_limit='30',rerank_top_n='8')
        allowed={'embedding_api_model','embedding_base_url','embedding_api_key','embedding_require_real','embedding_timeout',
                 'rerank_api_model','rerank_base_url','rerank_api_key','rerank_enabled','rerank_timeout','rerank_candidate_limit','rerank_top_n'}
        for section,values in unchanged_before.items():
            for name,value in values.items():
                if section!='key' or name not in allowed:assert config[section][name]==value
        provider.write_config(config)
    report.update(saved=True,chat_and_tts_credentials_unchanged=True,
                  note='Credentials saved only in ignored local system.conf; memory flag remains off pending patch/tests/migration.')
    serialized=json.dumps(report,ensure_ascii=False,indent=2)
    assert secret not in serialized
    (ROOT/'docs/siliconflow-memory-activation-2026-11-04.json').write_text(serialized,encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__,'message':'Paid model configuration not activated; inspect safe probe status.'}),flush=True)
        sys.exit(1)
