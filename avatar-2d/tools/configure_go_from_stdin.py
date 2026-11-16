"""Read a supplied key from stdin, probe first, then activate. Never log secrets."""
import json
import getpass
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'service'))
import provider_config
import bailian_speech


def main():
    print('Waiting for the provided key on stdin (not echoed).', flush=True)
    secret = (getpass.getpass('API Key (hidden): ') if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not secret:
        raise ValueError('missing input')
    original_tts = bailian_speech.settings()
    original_model = provider_config.public_settings()['model']
    data = {k:provider_config.PRESETS['opencode_go'][k] for k in ('model', 'base_url')}
    data.update(provider='opencode_go', api_key=secret)
    session = requests.Session()
    session.trust_env = False
    headers = {'X-Avatar-Client':'1'}
    base = 'http://127.0.0.1:8766'
    response = session.post(base+'/api/provider-test', json=data, headers=headers, timeout=45)
    result = response.json()
    report = dict(probe=result, saved=False, previous_model=original_model)
    if response.status_code == 200 and result.get('ok'):
        saved = session.post(base+'/api/provider', json=data, headers=headers, timeout=10)
        if saved.status_code != 200:
            report['save_failed'] = True
        else:
            public = saved.json()['provider']
            report.update(saved=True, provider=public['provider'], model=public['model'], base_url=public['base_url'],
                          tts_unchanged=bailian_speech.settings()==original_tts)
    else:
        report['probe_http'] = response.status_code
    # No API keys, headers, raw provider errors or submitted body in the evidence.
    data['api_key'] = '';secret = ''
    output = ROOT/'docs/opencode-go-activation.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__,'credentials_logged':False}),flush=True)
        sys.exit(1)
