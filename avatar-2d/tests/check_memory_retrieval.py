"""Local failure/ordering tests; --real exercises native MemoryStream with paid APIs."""
import argparse
import ast
import configparser
import json
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
sys.path.insert(0,str(ROOT/'service'))
import memory_retrieval as retrieval


def config():
    c=configparser.ConfigParser(interpolation=None)
    c['key']=dict(rerank_enabled='true',rerank_base_url='https://api.siliconflow.cn/v1',
        rerank_api_key='private-rerank-test',rerank_api_model='Pro/BAAI/bge-reranker-v2-m3',rerank_top_n='2',rerank_candidate_limit='30')
    return c


class Retrieval(unittest.TestCase):
    def setUp(self):
        retrieval.begin_retrieval()
        self.nodes=[SimpleNamespace(content='irrelevant',created=0),SimpleNamespace(content='relevant',created=1)]

    def test_paid_model_reorders_nodes_and_keeps_relevance_order(self):
        class HTTP:
            def post(inner,url,**kwargs):
                self.assertEqual(kwargs['json']['model'],'Pro/BAAI/bge-reranker-v2-m3')
                self.assertEqual(kwargs['headers']['Authorization'],'Bearer private-rerank-test')
                self.assertEqual(url,'https://api.siliconflow.cn/v1/rerank')
                return SimpleNamespace(status_code=200,json=lambda:{'results':[{'index':1,'relevance_score':.9},{'index':0,'relevance_score':.1}]})
        retrieval.LOCAL.http=HTTP()
        with patch.object(retrieval,'read_config',return_value=config()):
            rows=retrieval.rerank_nodes('query',self.nodes,2)
        self.assertIs(rows[0],self.nodes[1])
        self.assertEqual(retrieval.retrieval_metrics()['rerank_status'],'ok')

    def test_invalid_indices_preserve_real_vector_candidates_without_another_model(self):
        calls=[]
        class HTTP:
            def post(inner,url,**kwargs):
                calls.append(kwargs['json']['model'])
                return SimpleNamespace(status_code=200,json=lambda:{'results':[{'index':99,'relevance_score':.9}]})
        retrieval.LOCAL.http=HTTP()
        with patch.object(retrieval,'read_config',return_value=config()):
            self.assertEqual(retrieval.rerank_nodes('query',self.nodes,2),self.nodes)
        self.assertEqual(calls,['Pro/BAAI/bge-reranker-v2-m3'])
        self.assertEqual(retrieval.retrieval_metrics()['rerank_status'],'unavailable')

    def test_disabled_rerank_preserves_legacy_chronology(self):
        c=config();c['key']['rerank_enabled']='false'
        with patch.object(retrieval,'read_config',return_value=c):
            self.assertEqual(retrieval.rerank_nodes('query',list(reversed(self.nodes)),2),self.nodes)

    def test_native_strict_embedding_never_calls_mock_on_api_error(self):
        source=ast.parse((FAY/'simulation_engine/gpt_structure.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='get_text_embedding')
        namespace=dict(cfg=SimpleNamespace(embedding_require_real=True),List=list,__file__=str(FAY/'simulation_engine/gpt_structure.py'))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'native-get-embedding','exec'),namespace)
        with patch.object(retrieval,'strict_embedding',side_effect=RuntimeError('provider unavailable')):
            with self.assertRaisesRegex(RuntimeError,'provider unavailable'):namespace['get_text_embedding']('query')

    def test_invalid_vector_is_rejected(self):
        module=types.ModuleType('utils.api_embedding_service')
        module.get_embedding_service=lambda:SimpleNamespace(encode_text=lambda _: [float('nan')])
        with patch.dict(sys.modules,{'utils.api_embedding_service':module}):
            with self.assertRaises(ValueError):retrieval.strict_embedding('query')


def real():
    if hasattr(retrieval.LOCAL,'http'):del retrieval.LOCAL.http
    for name in ('FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','LANGCHAIN_API_KEY','LANGSMITH_API_KEY','OPENAI_API_KEY','EMBEDDING_API_KEY'):
        os.environ.pop(name,None)
    os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false')
    os.chdir(FAY)
    sys.path.insert(0,str(FAY))
    from utils import config_util as cfg
    cfg.load_config()
    assert cfg.embedding_api_model=='Pro/BAAI/bge-m3' and cfg.embedding_api_base_url=='https://api.siliconflow.cn/v1'
    assert cfg.embedding_require_real and cfg.embedding_api_key!=cfg.key_gpt_api_key
    from utils.api_embedding_service import get_embedding_service
    from genagents.modules.memory_stream import MemoryStream
    docs=['参观者希望讲解简洁，每次回答控制在两句话。','展馆停车场位于西侧入口。','今天餐厅提供面条和米饭。']
    vectors=get_embedding_service().encode_texts(docs)
    assert len(vectors)==3 and all(len(v)==1024 for v in vectors)
    nodes=[dict(node_id=i,node_type='observation',content=text,importance=5,created=0,last_retrieved=0,pointer_id=None) for i,text in enumerate(docs)]
    stream=MemoryStream(nodes,dict(zip(docs,vectors)))
    query='这位参观者喜欢怎样的讲解方式？'
    retrieval.begin_retrieval()
    answer=stream.retrieve([query],1,n_count=3,hp=[.8,.5,.5])
    assert answer[query][0].node_id==0
    metrics=retrieval.retrieval_metrics()
    assert metrics['rerank_status']=='ok' and metrics['embedding_calls']==1 and metrics['embedding_dimensions']==1024
    report=dict(status='NATIVE_PAID_EMBEDDING_RERANK_PASSED',embedding_model=cfg.embedding_api_model,
                native_memory_stream=True,relevant_document_rank=1,metrics=metrics,
                production_memory_written=False,synthetic_memory_in_process_only=True)
    (ROOT/'docs/memory-retrieval-native-validation-2026-11-04.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true');args=parser.parse_args()
    if args.real:real()
    else:unittest.main(argv=[sys.argv[0]],verbosity=2)
