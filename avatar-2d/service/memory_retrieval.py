"""Independent paid retrieval credentials and bounded reranking for native Fay memory."""
import math
import threading
import time

import requests

from provider_config import read_config

LOCAL=threading.local()


def begin_retrieval():
    LOCAL.metrics={'embedding_calls':0,'embedding_ms':0.0,'rerank_status':'not_called'}


def retrieval_metrics():
    return dict(getattr(LOCAL,'metrics',{}))


def strict_embedding(text):
    """Require a real provider vector; errors propagate instead of producing mock data."""
    if not isinstance(text,str) or not text.strip():raise ValueError('Empty embedding input')
    from utils.api_embedding_service import get_embedding_service
    started=time.perf_counter()
    vector=get_embedding_service().encode_text(text.replace('\n',' ').strip())
    if not isinstance(vector,list) or not vector or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in vector) or not any(vector):
        raise ValueError('Invalid embedding vector')
    metrics=getattr(LOCAL,'metrics',{})
    metrics.update(embedding_calls=metrics.get('embedding_calls',0)+1,
                   embedding_ms=round(metrics.get('embedding_ms',0)+(time.perf_counter()-started)*1000,3),
                   embedding_dimensions=len(vector))
    LOCAL.metrics=metrics
    return vector


def rerank_nodes(query,nodes,n_count):
    config=read_config();key=config['key']
    if not key.getboolean('rerank_enabled',fallback=False):
        return sorted(nodes,key=lambda node:node.created)
    if not nodes:return []
    candidates=list(nodes[:max(1,min(100,key.getint('rerank_candidate_limit',fallback=30)))])
    top_n=max(1,min(len(candidates),n_count,key.getint('rerank_top_n',fallback=8)))
    endpoint=key.get('rerank_base_url','').strip().rstrip('/')
    secret=key.get('rerank_api_key','').strip()
    model=key.get('rerank_api_model','').strip()
    metrics=getattr(LOCAL,'metrics',{})
    metrics.update(rerank_model=model,rerank_candidates=len(candidates),rerank_top_n=top_n)
    started=time.perf_counter()
    try:
        if not endpoint or not secret or not model:raise ValueError('Incomplete rerank configuration')
        # One session per thread avoids sharing mutable transport state with memory writers.
        if not hasattr(LOCAL,'http'):
            LOCAL.http=requests.Session();LOCAL.http.trust_env=False
        response=LOCAL.http.post(endpoint+'/rerank',headers={'Authorization':'Bearer '+secret},
            json=dict(model=model,query=query,documents=[n.content for n in candidates],top_n=top_n,return_documents=False),
            timeout=(3,max(1,min(20,key.getfloat('rerank_timeout',fallback=8)))),allow_redirects=False)
        if response.status_code!=200:raise RuntimeError('Rerank HTTP '+str(response.status_code))
        result=response.json()['results']
        if not isinstance(result,list) or not result:raise ValueError('Empty rerank response')
        indexes=[]
        for item in result:
            index=item['index'];score=item['relevance_score']
            if type(index) is not int or not 0<=index<len(candidates) or index in indexes or not math.isfinite(float(score)):
                raise ValueError('Invalid rerank response')
            indexes.append(index)
        # Preserve provider relevance order; do not sort by node creation time afterwards.
        ranked=sorted(result,key=lambda item:float(item['relevance_score']),reverse=True)[:top_n]
        metrics.update(rerank_status='ok',rerank_results=len(ranked))
        return [candidates[item['index']] for item in ranked]
    except Exception as exc:
        # Use the existing real-vector candidate ordering, never another/free model.
        metrics.update(rerank_status='unavailable',rerank_error_type=type(exc).__name__)
        return candidates[:top_n]
    finally:
        metrics['rerank_ms']=round((time.perf_counter()-started)*1000,3)
        LOCAL.metrics=metrics


def public_settings(config=None):
    config=config if config is not None else read_config();key=config['key']
    return dict(embedding_model=key.get('embedding_api_model',''),embedding_base_url=key.get('embedding_base_url',''),
        embedding_independent_key=bool(key.get('embedding_api_key','')),require_real_vectors=key.getboolean('embedding_require_real',fallback=False),
        rerank_enabled=key.getboolean('rerank_enabled',fallback=False),rerank_model=key.get('rerank_api_model',''),
        rerank_base_url=key.get('rerank_base_url',''),rerank_configured=bool(key.get('rerank_api_key','')),
        candidate_limit=key.getint('rerank_candidate_limit',fallback=30),top_n=key.getint('rerank_top_n',fallback=8))
