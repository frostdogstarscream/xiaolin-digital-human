"""Reproducible native patches; backup code only, never configuration secrets."""
import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'


def main():
    backup=ROOT/'runtime/memory-retrieval-patches'/datetime.now().strftime('%Y%m%d-%H%M%S')
    changes=[]
    def patch(relative,transform):
        path=FAY/relative;old=path.read_text(encoding='utf-8-sig');new=transform(old)
        ast.parse(new)
        if old==new:return
        target=backup/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(old,encoding='utf-8')
        path.write_text(new,encoding='utf-8')
        changes.append(dict(file=relative,before_sha256=hashlib.sha256(old.encode()).hexdigest(),after_sha256=hashlib.sha256(new.encode()).hexdigest()))
    def replace(text,old,new):
        assert text.count(old)==1,old[:100]
        return text.replace(old,new)
    def config(text):
        if '# local-paid-memory-config-v1' in text:return text
        text=replace(text,'embedding_api_key = None','embedding_api_key = None\nembedding_require_real = False\nembedding_timeout = 8')
        text=replace(text,'    global embedding_api_key','    global embedding_api_key\n    global embedding_require_real\n    global embedding_timeout')
        return replace(text,'    embedding_api_key = key_gpt_api_key  # 复用 LLM api_key',
            '''    # local-paid-memory-config-v1
    embedding_api_key = system_config.get('key', 'embedding_api_key', fallback='').strip() or key_gpt_api_key
    embedding_require_real = system_config.getboolean('key', 'embedding_require_real', fallback=False)
    embedding_timeout = system_config.getfloat('key', 'embedding_timeout', fallback=8)''')
    patch('utils/config_util.py',config)
    def api(text):
        if '# local-paid-memory-http-v1' in text:return text
        text=replace(text,'            self.timeout = 60  # API 请求超时时间（秒），默认 60 秒',
            '''            # local-paid-memory-http-v1
            self.timeout = max(1, min(30, getattr(cfg, 'embedding_timeout', 8)))
            self.http = requests.Session()
            self.http.trust_env = False''')
        text=replace(text,'            self.max_retries = 2  # 最大重试次数','            self.max_retries = 0 if getattr(cfg, "embedding_require_real", False) else 2')
        return text.replace('response = requests.post(url,','response = self.http.post(url,')
    patch('utils/api_embedding_service.py',api)
    def gpt(text):
        if '# local-paid-memory-strict-v1' in text:return text
        old='  global _known_embedding_dim\n  try:'
        text=replace(text,old,'''  global _known_embedding_dim
  # local-paid-memory-strict-v1
  if getattr(cfg, 'embedding_require_real', False):
    import sys
    from pathlib import Path
    service_path = str(Path(__file__).resolve().parents[5]/'avatar-2d/service')
    if service_path not in sys.path: sys.path.insert(0, service_path)
    from memory_retrieval import strict_embedding
    vector = strict_embedding(text)
    _known_embedding_dim = len(vector)
    return vector
  try:''')
        # Importance/reflection use the configured small role's headers and mode too.
        text=replace(text,'        _client = openai.OpenAI(api_key=api_key, base_url=base_url,',
            '''        import sys
        from pathlib import Path
        service_path = str(Path(__file__).resolve().parents[5]/'avatar-2d/service')
        if service_path not in sys.path: sys.path.insert(0, service_path)
        from provider_config import request_headers
        _client = openai.OpenAI(api_key=api_key, base_url=base_url, default_headers=request_headers(base_url, 'fay-memory-helper'),''')
        text=replace(text,'  # 处理o1-preview模型', '''  # Native memory helpers follow the small-role mode, not big-model reasoning.
  from provider_config import generation_options
  opts = generation_options('small', cfg.gpt_base_url, model)
  generation = {'reasoning_effort': opts['reasoning_effort']} if 'reasoning_effort' in opts else {}
  if 'thinking' in opts: generation['extra_body'] = {'thinking': opts['thinking']}
  # 处理o1-preview模型''')
        text=replace(text,'      messages=[{"role": "user", "content": prompt}],\n      max_tokens=max_tokens,\n      temperature=0.7\n    )',
            '      messages=[{"role": "user", "content": prompt}],\n      max_tokens=max_tokens,\n      temperature=0.7,\n      **generation\n    )')
        return text
    patch('simulation_engine/gpt_structure.py',gpt)
    def stream(text):
        if '# local-memory-rerank-v1' in text:return text
        return replace(text,'      master_nodes = sorted(master_nodes, key=lambda node: node.created, reverse=False)',
            '''      # local-memory-rerank-v1
      from pathlib import Path
      service_path = str(Path(__file__).resolve().parents[6]/'avatar-2d/service')
      if service_path not in sys.path: sys.path.insert(0, service_path)
      from memory_retrieval import rerank_nodes
      master_nodes = rerank_nodes(focal_pt, master_nodes, n_count)''')
    patch('genagents/modules/memory_stream.py',stream)
    def strict_append(text):
        if '# local-memory-strict-append-v1' in text:return text
        start=text.index('  def _add_node(');end=text.index('\n  def remember(',start)
        part=text[start:end]
        part=replace(part,'    self.seq_nodes += [new_node]', '''    # local-memory-strict-append-v1
    try:
      prepared_embedding = get_text_embedding(content)
    except Exception:
      from utils import config_util as cfg
      if getattr(cfg, 'embedding_require_real', False): raise
      prepared_embedding = []
    self.seq_nodes += [new_node]''')
        begin=part.index('    try:\n        self.embeddings[content] = get_text_embedding(content)')
        finish=part.index('\n    return new_node',begin)
        part=part[:begin]+'    self.embeddings[content] = prepared_embedding\n'+part[finish:]
        return text[:start]+part+text[end:]
    patch('genagents/modules/memory_stream.py',strict_append)
    def cognitive(text):
        if '# local-memory-retrieval-metrics-v1' in text:return text
        text=replace(text,'    memory_context = ""\n    skip_memory_retrieve =',
            '''    memory_context = ""
    # local-memory-retrieval-metrics-v1
    from memory_retrieval import begin_retrieval, retrieval_metrics
    begin_retrieval()
    skip_memory_retrieve =''')
        text=replace(text,'    timing.mark("memory_ready",memory_context_chars=len(memory_context))',
            '    timing.mark("memory_ready",memory_context_chars=len(memory_context),memory_retrieval=retrieval_metrics())')
        for label in ('对话','观察'):
            old=f'            util.log(1, f"生成{label}嵌入失败，使用空向量: {{str(e)}}")\n            embedding = []'
            new=f'''            if getattr(cfg, 'embedding_require_real', False):
                util.log(1, '付费向量服务不可用，跳过本条{label}记忆写入')
                return
'''+old
            text=replace(text,old,new)
        return text
    patch('llm/nlp_cognitive_stream.py',cognitive)
    def external(text):
        if '# local-memory-external-strict-v1' in text:return text
        return replace(text,'        util.log(1, f"[memory_service] 生成 embedding 失败，使用空向量: {str(e)}")',
            '''        # local-memory-external-strict-v1
        from utils import config_util as cfg
        if getattr(cfg, 'embedding_require_real', False):
            return {"ok": False, "error": "Paid embedding unavailable; memory was not written"}
        util.log(1, f"[memory_service] 生成 embedding 失败，使用空向量: {str(e)}")''')
    patch('core/memory_service.py',external)
    installed=[dict(file=name,sha256=hashlib.sha256((FAY/name).read_bytes()).hexdigest()) for name in (
        'utils/config_util.py','utils/api_embedding_service.py','simulation_engine/gpt_structure.py',
        'genagents/modules/memory_stream.py','llm/nlp_cognitive_stream.py','core/memory_service.py')]
    output=ROOT/'docs/memory-retrieval-install-2026-11-04.json'
    output.write_text(json.dumps(dict(changes=changes,installed=installed,code_backups=str(ROOT/'runtime/memory-retrieval-patches')),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Patched native files:',len(changes),flush=True)


if __name__=='__main__':main()
