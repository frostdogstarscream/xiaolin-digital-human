"""Fresh provider configuration per LLM request; no cached credentials or model."""
import contextvars
import uuid

from provider_config import generation_options, request_headers

SESSION = contextvars.ContextVar('fay_llm_session', default=None)


def set_session(username, conversation_id):
    # Background execution and final callbacks already carry this same conversation ID.
    SESSION.set(str(conversation_id) if conversation_id else str(username))


def make_llm(cfg, role='small', streaming=True, session_id=None):
    from langchain_openai import ChatOpenAI
    cfg.load_config()
    big = role == 'big' and bool(cfg.big_model_engine)
    endpoint = (cfg.big_model_base_url or cfg.gpt_base_url) if big else cfg.gpt_base_url
    api_key = (cfg.big_model_api_key or cfg.key_gpt_api_key) if big else cfg.key_gpt_api_key
    model = cfg.big_model_engine if big else cfg.gpt_model_engine
    options = generation_options('big' if big else 'small', endpoint, model)
    arguments = {}
    if 'reasoning_effort' in options:
        arguments['reasoning_effort'] = options['reasoning_effort']
    if 'thinking' in options:
        arguments['extra_body'] = {'thinking': options['thinking']}
    return ChatOpenAI(model=model, base_url=endpoint, api_key=api_key,
                      streaming=streaming, timeout=120 if big else 60,
                      max_retries=2 if big else 1,
                      default_headers=request_headers(endpoint, session_id or SESSION.get() or uuid.uuid4().hex),
                      **arguments)


class ReloadableLLM:
    def __init__(self, factory):
        self.factory = factory

    def stream(self, *args, **kwargs):
        # Keep one provider instance throughout this response's stream.
        return self.factory('small', streaming=True).stream(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        return self.factory('small', streaming=False).invoke(*args, **kwargs)
