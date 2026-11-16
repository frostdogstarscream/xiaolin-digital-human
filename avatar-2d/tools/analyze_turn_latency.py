"""Read an existing production trace; calibrate client construction without cloud calls."""
import hashlib
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
import provider_config as provider
from fay_llm_runtime import make_llm


def main():
    trace_path = ROOT / 'runtime/turn-timings/81c39bcf00804eb3aaede62ff7eaedcd.json'
    trace = json.loads(trace_path.read_text(encoding='utf-8'))
    original_path = ROOT / 'docs/role-reasoning-dialogue-validation-2026-11-04.json'
    original = json.loads(original_path.read_text(encoding='utf-8'))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    health = json.load(opener.open('http://127.0.0.1:8766/api/health', timeout=10))
    job = next(j for j in health['jobs'] if j['job_id'] == '5a501f10926f4cbfa06b63a04a5943c1')
    # Original observer stored durations rounded to milliseconds, not its wall-clock origin.
    request_unix = job['started_at'] - original['first_playback_callback_seconds']
    m = trace['marks']
    at = lambda name: trace['started_unix'] + m[name]
    stages = dict(
        entry_before_question=at('question_enter') - request_unix,
        context_and_prompt=m['llm_request_start'] - m['question_enter'],
        small_model_factory_and_first_content=m['llm_first_text'] - m['llm_request_start'],
        text_buffer=m['first_sentence_enqueued'] - m['llm_first_text'],
        sentence_to_tts_ingress=job['received_at'] - at('first_sentence_enqueued'),
        tts_first_pcm=job['first_delta_at'] - job['received_at'],
        pcm_to_playback_callback=job['started_at'] - job['first_delta_at'])
    from langchain_openai import ChatOpenAI  # Exclude cold module import from construction calibration.
    config = provider.read_config()
    key = config['key']
    cfg = SimpleNamespace(big_model_engine=key.get('big_model_engine', ''),
        big_model_base_url=key.get('big_model_base_url', ''), big_model_api_key=key.get('big_model_api_key', ''),
        gpt_base_url=key.get('gpt_base_url', ''), gpt_model_engine=key.get('gpt_model_engine', ''),
        key_gpt_api_key=key.get('gpt_api_key', ''), load_config=lambda: None)
    calibration = []
    for _ in range(3):
        started = time.perf_counter()
        llm = make_llm(cfg)
        calibration.append(time.perf_counter() - started)
        llm.root_client.close()
        import asyncio
        asyncio.run(llm.root_async_client.close())
    report = dict(source_trace=str(trace_path.relative_to(ROOT)), trace=trace,
        source_dialogue=str(original_path.relative_to(ROOT)), original_dialogue=original,
        retained_job=job, request_unix_reconstructed=request_unix,
        clock_note='Entry time reconstructed from playback timestamp minus millisecond-rounded observer duration; approximately +/- 1ms. Other stage deltas use native clocks.',
        route='direct', model_calls={'small':1,'big':0,'separate_intent_model':0},
        stages_seconds={k:round(v,6) for k,v in stages.items()},
        first_answer_observed_seconds=original['first_answer_text_seconds'],
        first_playback_seconds=round(sum(stages.values()),6),
        visible_answer_relay_after_sentence_seconds=round(request_unix + original['first_answer_text_seconds'] - at('first_sentence_enqueued'),6),
        context_breakdown_seconds={
            'agent':m['agent_ready']-m['question_enter'],
            'role':m['role_ready']-m['agent_ready'],
            'memory_skipped':m['memory_ready']-m['memory_start'],
            'history':m['history_ready']-m['resources_ready'],
            'prompt_build':m['prompt_ready']-m['prompt_build_start']},
        client_construction_calibration_seconds=calibration,
        client_construction_calibration_median_seconds=statistics.median(calibration),
        calibration_scope='Separate local process, warm module import, cfg.load_config mocked as no-op; constructs SDK/HTTP clients without any model requests. Not original-turn measured attribution.',
        cloud_calls_this_analysis=0, configuration_changed=False)
    serialized=json.dumps(report,ensure_ascii=False,indent=2)
    assert key['gpt_api_key'] not in serialized
    output=ROOT/'docs/role-reasoning-latency-analysis-2026-11-04.json'
    output.write_text(serialized,encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('stages_seconds','client_construction_calibration_seconds','first_playback_seconds','model_calls')},ensure_ascii=True),flush=True)


if __name__ == '__main__':
    main()
