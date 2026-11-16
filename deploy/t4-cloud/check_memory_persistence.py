"""Reload the newly saved cloud memory through Fay's native agent implementation."""
import hashlib,json,os,sys
from pathlib import Path
native=Path('/app/fay-ue4/runtime/fay-local/app')
os.chdir(native);sys.path.insert(0,str(native));sys.path.insert(0,'/app/avatar-2d/service')
from utils import config_util as cfg
cfg.load_config()
assert cfg.config['memory']['use_bionic_memory']
from llm.nlp_cognitive_stream import create_agent
expected=json.loads(Path('/opt-evidence/memory-before-restart.json').read_text())
agent=create_agent('Avatar2D')
nodes=agent.memory_stream.seq_nodes;embeddings=agent.memory_stream.embeddings
assert len(nodes)==expected['nodes'] and len(embeddings)==expected['embeddings']
folder=Path('/shared/data/native-memory/Avatar2D/memory_stream')
assert hashlib.sha256((folder/'nodes.json').read_bytes()).hexdigest()==expected['nodes_sha256']
assert all(len(v)==1024 for v in embeddings.values())
assert all('"gesture"' not in n.content and 'plan_id' not in n.content for n in nodes)
result=dict(status='PASSED',native_agent_reload=True,nodes=len(nodes),embeddings=len(embeddings),dimensions=1024,
    saved_before_restart=expected,metadata_leak=False)
Path('/app/deployment/memory-persistence-check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
