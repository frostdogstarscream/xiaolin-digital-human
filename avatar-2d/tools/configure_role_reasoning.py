"""Apply the user's authorized DeepSeek role modes; retain credentials and speech settings."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
import provider_config as provider


def main():
    with provider.LOCK:
        config = provider.read_config()
        original = {name: dict(config[name]) for name in config.sections()}
        key = config['key']
        endpoint = provider.PRESETS['opencode_go']['base_url']
        model = 'deepseek-v4.1-flash'
        assert key.get('gpt_model_engine') == key.get('big_model_engine') == model
        assert key.get('gpt_base_url', '').rstrip('/') == endpoint
        assert key.get('big_model_base_url', '').rstrip('/') == endpoint
        for role, thinking, effort in (('small', 'disabled', 'low'), ('big', 'enabled', 'medium')):
            config['llm_generation:' + role] = dict(base_url=endpoint, model=model, thinking=thinking, reasoning_effort=effort)
        assert all(dict(config[name]) == values for name, values in original.items() if not name.startswith('llm_generation:'))
        provider.write_config(config)
    report = dict(provider=provider.public_settings(), credentials_changed=False, tts_settings_changed=False,
                  unrelated_settings_changed=False, source='Explicit user request',
                  note='DeepSeek maps medium to high; disabled thinking overrides low.')
    output = ROOT / 'docs' / 'role-reasoning-activation-2026-11-04.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
