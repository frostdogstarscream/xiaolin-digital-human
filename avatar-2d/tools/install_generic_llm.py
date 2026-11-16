"""Reproducible narrow patches for the retained local Fay installation."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAY = ROOT.parent/'fay-ue4/runtime/fay-local/app'
sys.path.insert(0, str(ROOT/'service'))
import provider_config


def main():
    backup = ROOT/'runtime/llm-provider-patches'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    changes = []

    def write(relative, text):
        path = FAY/relative
        before = path.read_text(encoding='utf-8-sig')
        if before == text:
            return
        target = backup/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before, encoding='utf-8')
        path.write_text(text, encoding='utf-8')
        changes.append(dict(file=relative, before_sha256=hashlib.sha256(before.encode()).hexdigest(), after_sha256=hashlib.sha256(text.encode()).hexdigest()))

    file = 'llm/execution_manager.py'
    text = (FAY/file).read_text(encoding='utf-8-sig')
    if '# local-generic-llm-factory-v1' not in text:
        start = text.index('def _get_llm_instance(')
        end = text.index('\n\n# ---------------------------------------------------------------------------', start)
        replacement = '''# local-generic-llm-factory-v1
def _get_llm_instance(role="small", streaming=True, session_id=None):
    import sys
    from pathlib import Path
    service_path = str(Path(__file__).resolve().parents[5]/"avatar-2d/service")
    if service_path not in sys.path:
        sys.path.insert(0, service_path)
    from fay_llm_runtime import make_llm
    return make_llm(cfg, role, streaming, session_id)
'''
        text = text[:start]+replacement+text[end:]
        old = 'big_llm = _get_llm_instance(llm_role, streaming=False)'
        assert text.count(old) == 1
        text = text.replace(old, 'big_llm = _get_llm_instance(llm_role, streaming=False, session_id=state.conversation_id)')
        write(file, text)

    file = 'gui/flask_server.py'
    text = (FAY/file).read_text(encoding='utf-8-sig')
    if '# local-generic-llm-proxy-headers-v1' not in text:
        old = '            headers = _build_llm_proxy_headers(api_key, stream_requested=stream_requested)'
        assert text.count(old) == 1
        text = text.replace(old, old+'''
            # local-generic-llm-proxy-headers-v1
            import sys
            from pathlib import Path
            adapter_path = str(Path(__file__).resolve().parents[5]/"avatar-2d/service")
            if adapter_path not in sys.path:
                sys.path.insert(0, adapter_path)
            from provider_config import request_headers
            headers.update(request_headers(config_util.gpt_base_url,
                data.get('user') or data.get('username') or request.headers.get('x-opencode-session') or 'fay-local-chat'))
''')
        write(file, text)

    if '# local-role-generation-proxy-v1' not in text:
        old = '            trace_state = _start_langsmith_proxy_trace(llm_url, payload)'
        assert text.count(old) == 1
        text = text.replace(old, '''            # local-role-generation-proxy-v1
            from provider_config import generation_options
            for name, value in generation_options('small', config_util.gpt_base_url, model_name).items():
                payload.setdefault(name, value)
''' + old)
        write(file, text)

    file = 'llm/nlp_cognitive_stream.py'
    text = (FAY/file).read_text(encoding='utf-8-sig')
    if '# local-generic-llm-reload-v1' not in text:
        old = '\nllm = _get_llm_instance("small", streaming=True)'
        assert text.count(old) == 1
        text = text.replace(old, '''
# local-generic-llm-reload-v1
# The existing factory installs the local adapter path. No network calls here.
_get_llm_instance("small", streaming=True)
from fay_llm_runtime import ReloadableLLM, set_session
llm = ReloadableLLM(_get_llm_instance)''')
        old = '    conversation_id = sm.get_conversation_id(username)'
        assert text.count(old) == 1
        text = text.replace(old, old+'\n    set_session(username, conversation_id)')
        old = 'small_llm = _get_llm_instance("small", streaming=True)'
        assert text.count(old) == 1
        text = text.replace(old, 'small_llm = _get_llm_instance("small", streaming=True, session_id=conv_id)')
        write(file, text)

    for file in ('gui/templates/index.html', 'gui/templates/setting.html'):
        text = (FAY/file).read_text(encoding='utf-8-sig')
        if 'local-generic-llm-settings-link' not in text:
            marker = '<div class="main_left_menu">'
            start = text.index(marker)
            end = text.index('</ul>', start)
            text = text[:end]+'''<li data-local="local-generic-llm-settings-link"><a href="http://127.0.0.1:8766/models" target="_blank" rel="noreferrer"><span>大模型配置 ↗</span></a></li>
        '''+text[end:]
            write(file, text)

    with provider_config.LOCK:
        config = provider_config.read_config()
        before = dict(config['key'])
        provider_config.pin_tts(config)
        if dict(config['key']) != before:
            provider_config.write_config(config)
    # Only public metadata and code hashes. Never archive system.conf credentials.
    installed = []
    for file in ('llm/execution_manager.py','llm/nlp_cognitive_stream.py','gui/flask_server.py','gui/templates/index.html','gui/templates/setting.html'):
        installed.append(dict(file=file, sha256=hashlib.sha256((FAY/file).read_bytes()).hexdigest()))
    report = dict(patches=changes, installed=installed, code_backups=str(ROOT/'runtime/llm-provider-patches'),
                  public=provider_config.public_settings(), config_secrets_returned=False)
    out = ROOT/'docs/generic-llm-install.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Generic LLM integration installed; code files patched:', len(changes))
    print('Active LLM retained:', report['public']['model'])


if __name__ == '__main__':
    main()
