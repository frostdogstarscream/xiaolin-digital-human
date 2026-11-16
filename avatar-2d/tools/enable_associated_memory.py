"""Enable native memory only after successful paid retrieval validation and migration."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
import provider_config as provider
from memory_retrieval import public_settings


def main():
    validation=json.loads((ROOT/'docs/memory-retrieval-native-validation-2026-11-04.json').read_text(encoding='utf-8'))
    migration=json.loads((ROOT/'docs/memory-embedding-migration-2026-11-04.json').read_text(encoding='utf-8'))
    assert validation['status']=='NATIVE_PAID_EMBEDDING_RERANK_PASSED'
    assert validation['metrics']['rerank_status']=='ok' and migration['using_mock_vectors'] is False
    assert migration['model']=='Pro/BAAI/bge-m3'
    conf_hash=hashlib.sha256((provider.FAY/'system.conf').read_bytes()).hexdigest()
    target=provider.FAY/'config.json'
    previous=json.loads(target.read_text(encoding='utf-8-sig'))
    current=json.loads(json.dumps(previous))
    current.setdefault('memory',{})['use_bionic_memory']=True
    temporary=target.with_suffix('.memory-enable.tmp')
    temporary.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
    assert hashlib.sha256((provider.FAY/'system.conf').read_bytes()).hexdigest()==conf_hash
    report=dict(enabled=True,user_isolation=current['memory'].get('isolate_by_user'),retrieval=public_settings(),
                chat_and_tts_config_unchanged=True,previous_enabled=previous.get('memory',{}).get('use_bionic_memory'),
                migration_users=migration['users'])
    (ROOT/'docs/associated-memory-enabled-2026-11-04.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
