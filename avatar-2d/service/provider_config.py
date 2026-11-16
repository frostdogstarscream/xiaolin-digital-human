"""Local OpenAI-compatible LLM profiles. Secrets never appear in public metadata."""
import configparser
import hashlib
import ipaddress
import os
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

FAY = Path(__file__).resolve().parents[2]/'fay-ue4/runtime/fay-local/app'
LOCK = threading.RLock()
PRESETS = {
    'bailian': {'label': '百炼 · 通义千问', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen-plus'},
    'opencode_go': {'label': 'OpenCode Go · DeepSeek Flash', 'base_url': 'https://opencode.ai/inference/go/openai/v1', 'model': 'deepseek-v4.1-flash'},
    'custom': {'label': '自定义 OpenAI 兼容接口', 'base_url': '', 'model': ''},
}


class ConfigurationError(ValueError):
    pass


def read_config(path=None):
    config = configparser.ConfigParser(interpolation=None)
    config.read(path or FAY/'system.conf', encoding='utf-8-sig')
    if not config.has_section('key'):
        config.add_section('key')
    return config


def write_config(config, path=None):
    path = Path(path or FAY/'system.conf')
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w', encoding='utf-8') as output:
            config.write(output)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def bailian_url(endpoint):
    u = urlsplit(endpoint)
    return u.scheme == 'https' and (u.hostname in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com') or (u.hostname or '').endswith('.maas.aliyuncs.com'))


def infer_provider(endpoint):
    if bailian_url(endpoint):
        return 'bailian'
    if urlsplit(endpoint).hostname == 'opencode.ai':
        return 'opencode_go'
    return 'custom'


def normalize_endpoint(value):
    if not isinstance(value, str):
        raise ConfigurationError('请输入接口基础地址')
    value = value.strip().rstrip('/')
    if value.endswith('/chat/completions'):
        value = value[:-len('/chat/completions')]
    try:
        u = urlsplit(value)
        port = u.port
        host = u.hostname
    except ValueError:
        raise ConfigurationError('接口地址格式不正确') from None
    loopback = host == 'localhost'
    try:
        loopback = loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if (not host or u.username or u.password or u.query or u.fragment or
            re.search(r'[\s\\\x00-\x1f\x7f]', value) or len(value) > 500 or
            not (u.scheme == 'https' or u.scheme == 'http' and loopback)):
        raise ConfigurationError('请使用 HTTPS 基础地址；本机 localhost／127.0.0.1 可使用 HTTP。地址中不能包含密钥或查询参数。')
    if u.path.endswith(('/messages', '/responses')):
        raise ConfigurationError('当前支持 Chat Completions 协议，请填写对应的基础地址')
    return value


def active_provider(config):
    key = config['key']
    name = key.get('llm_provider', '')
    return name if name in PRESETS else infer_provider(key.get('gpt_base_url', ''))


def profile(config, provider):
    section = 'llm_profile:'+provider
    if active_provider(config) == provider:
        key = config['key']
        return dict(base_url=key.get('gpt_base_url', ''), model=key.get('gpt_model_engine', ''), api_key=key.get('gpt_api_key', ''))
    if section in config:
        return dict(config[section])
    return dict(PRESETS[provider])


def generation_options(role, endpoint, model, config=None):
    """Role options only apply to the exact model/endpoint they were saved for."""
    config = config if config is not None else read_config()
    section = 'llm_generation:' + ('big' if role == 'big' else 'small')
    if section not in config:
        return {}
    saved = config[section]
    if saved.get('base_url', '').rstrip('/') != endpoint.rstrip('/') or saved.get('model') != model:
        return {}
    options = {}
    effort = saved.get('reasoning_effort', '')
    if effort in ('none', 'minimal', 'low', 'medium', 'high', 'max', 'xhigh'):
        options['reasoning_effort'] = effort
    thinking = saved.get('thinking', '')
    if thinking in ('enabled', 'disabled'):
        options['thinking'] = {'type': thinking}
    return options


def generation_metadata(role, endpoint, model, config):
    options = generation_options(role, endpoint, model, config)
    thinking = options.get('thinking', {}).get('type', 'default')
    effort = options.get('reasoning_effort', 'default')
    effective = None if thinking == 'disabled' or thinking == 'default' and effort == 'none' else effort
    if effective == 'medium' and model.startswith('deepseek-v4'):
        effective = 'high'
    return dict(thinking=thinking, reasoning_effort=effort, effective_reasoning_effort=effective)


def public_settings(path=None):
    config = read_config(path)
    key = config['key']
    provider = active_provider(config)
    profiles = {}
    for name, preset in PRESETS.items():
        saved = profile(config, name)
        profiles[name] = dict(label=preset['label'], base_url=saved.get('base_url', ''), model=saved.get('model', ''), configured=bool(saved.get('api_key', '').strip()))
    big_model = key.get('big_model_engine', '').strip()
    big_endpoint = key.get('big_model_base_url', '').strip() or key.get('gpt_base_url', '')
    return dict(provider=provider, label=PRESETS.get(provider, PRESETS['custom'])['label'],
                configured=bool(key.get('gpt_api_key', '').strip()), model=key.get('gpt_model_engine', ''),
                base_url=key.get('gpt_base_url', ''), protocol='openai_chat_completions',
                tts=key.get('tts_module', ''), profiles=profiles,
                big_model_configured=bool(big_model),
                collaboration=dict(mode='dual' if big_model else 'single',
                    small_model=key.get('gpt_model_engine', ''), big_model=big_model,
                    big_base_url=big_endpoint if big_model else '',
                    small_generation=generation_metadata('small', key.get('gpt_base_url', ''), key.get('gpt_model_engine', ''), config),
                    big_generation=generation_metadata('big', big_endpoint, big_model, config) if big_model else None,
                    same_model_placeholder=bool(big_model and big_model==key.get('gpt_model_engine', '') and big_endpoint==key.get('gpt_base_url', ''))))


def resolve_submission(data, config):
    if not isinstance(data, dict):
        raise ConfigurationError('配置内容格式不正确')
    provider = data.get('provider') or infer_provider(data.get('base_url', ''))
    if provider not in PRESETS:
        raise ConfigurationError('请选择支持的服务或自定义兼容接口')
    saved = profile(config, provider)
    endpoint = normalize_endpoint(data.get('base_url', saved.get('base_url', '')))
    model = data.get('model', saved.get('model', ''))
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,159}', model.strip()):
        raise ConfigurationError('模型 ID 格式不正确，可包含字母、数字、点、斜线、冒号、下划线和短横线')
    if provider == 'bailian' and not bailian_url(endpoint):
        raise ConfigurationError('百炼预设需使用百炼官方地址；其他服务请选择自定义')
    if provider == 'opencode_go' and urlsplit(endpoint).hostname != 'opencode.ai':
        raise ConfigurationError('OpenCode Go 预设需使用 opencode.ai 地址')
    key = data.get('api_key', '')
    if not isinstance(key, str):
        raise ConfigurationError('API Key 格式不正确')
    key = key.strip()
    if not key:
        # Never forward another host's saved key to a newly entered URL.
        if saved.get('base_url', '').rstrip('/') != endpoint:
            raise ConfigurationError('接口地址已更换，请重新输入该接口的 API Key')
        key = saved.get('api_key', '').strip()
    if not key:
        raise ConfigurationError('请在本机输入此服务的 API Key；无需密钥的本地服务可填写 EMPTY')
    if len(key) > 4096 or re.search(r'[^\x21-\x7e]', key):
        raise ConfigurationError('API Key 中不能包含空格、换行或说明文字')
    return dict(provider=provider, base_url=endpoint, model=model.strip(), api_key=key)


def pin_tts(config):
    """One-way legacy migration, before replacing the formerly shared GPT key."""
    key = config['key']
    if 'bailian_tts_api_key' not in key:
        key['bailian_tts_api_key'] = key.get('gpt_api_key', '') if bailian_url(key.get('gpt_base_url', '')) else ''
    if not key.get('bailian_tts_base_url', '').strip():
        key['bailian_tts_base_url'] = key.get('gpt_base_url', '') if bailian_url(key.get('gpt_base_url', '')) else PRESETS['bailian']['base_url']


def save_settings(data, path=None):
    with LOCK:
        config = read_config(path)
        submitted = resolve_submission(data, config)
        previous = active_provider(config)
        if previous in PRESETS:
            config['llm_profile:'+previous] = profile(config, previous)
        pin_tts(config)
        config['llm_profile:'+submitted['provider']] = {k: submitted[k] for k in ('api_key', 'base_url', 'model')}
        config['key'].update(llm_provider=submitted['provider'], gpt_api_key=submitted['api_key'],
                             gpt_base_url=submitted['base_url'], gpt_model_engine=submitted['model'])
        write_config(config, path)
        return public_settings(path)


def set_collaboration(mode, path=None):
    """Enable native dual-role scheduling with an independent primary-model snapshot."""
    if mode not in ('dual_primary_placeholder', 'single'):
        raise ConfigurationError('请选择同模型占位协同或单模型模式')
    with LOCK:
        config = read_config(path)
        key = config['key']
        if mode == 'single':
            # Retain the independent endpoint/key; only the native mode switch changes.
            key['big_model_engine'] = ''
        else:
            primary = resolve_submission(dict(provider=active_provider(config),
                base_url=key.get('gpt_base_url',''), model=key.get('gpt_model_engine','')), config)
            key.update(big_model_engine=primary['model'], big_model_base_url=primary['base_url'],
                       big_model_api_key=primary['api_key'])
        write_config(config, path)
        return public_settings(path)


def request_headers(endpoint, session_id):
    headers = {'User-Agent': 'Fay-DigitalPresenter/1.0'}
    if urlsplit(endpoint).hostname == 'opencode.ai':
        headers['x-opencode-session'] = 'fay-'+hashlib.sha256(str(session_id).encode()).hexdigest()[:32]
    return headers
