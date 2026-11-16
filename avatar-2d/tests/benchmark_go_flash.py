"""Bounded, sequential text-only Go benchmark; reads credentials without saving them."""
import asyncio
import argparse
import hashlib
import json
import re
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from provider_config import FAY, PRESETS, profile, read_config, request_headers

CASES = [
    ('mimo-low', 'mimo-v2.6-flash', {'reasoning_effort': 'low'}),
    ('qwen-low', 'qwen3.8-flash', {'reasoning_effort': 'low'}),
    ('qwen-low-off', 'qwen3.8-flash', {'reasoning_effort': 'low', 'enable_thinking': False}),
]
PROMPTS = [
    '你好，小霖，请介绍一下你自己。',
    '参观时应该注意哪些基本礼仪？',
    '我只有十分钟，应该怎样安排参观？',
    '我有点听不清，你能用简单的话解释什么是数字人吗？',
    '谢谢你的讲解，我准备离开了。',
]
SYSTEM = '你是数字人讲解员小霖。请用简体中文直接回答，每次两句，总计40至70个汉字。第一句不少于20个汉字。语气自然，适合朗读，不使用列表和Markdown。不要虚构具体场馆信息。'


async def probe(client, endpoint, key, case, question, round_index, session_id):
    label, model, parameters = case
    body = dict(model=model, stream=True, max_tokens=1024,
                stream_options={'include_usage': True},
                messages=[{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': question}],
                **parameters)
    headers = request_headers(endpoint, session_id)
    headers['Authorization'] = 'Bearer ' + key
    result = dict(case=label, requested_model=model, parameters=parameters, round=round_index,
                  question=question, request_body=body, events=[], usage=None, ok=False)
    start = time.perf_counter()
    content = ''
    reasoning_chars = 0
    saw_done = False
    try:
        async with client.post(endpoint + '/chat/completions', json=body, headers=headers,
                               allow_redirects=False) as response:
            result['http_status'] = response.status
            result['headers_ms'] = round((time.perf_counter() - start) * 1000, 2)
            if response.status != 200:
                error = (await response.text())[:2000].replace(key, '[REDACTED]')
                result['error'] = error
                return result
            async for raw in response.content:
                line = raw.decode('utf-8').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                now = round((time.perf_counter() - start) * 1000, 2)
                if data == '[DONE]':
                    saw_done = True
                    break
                chunk = json.loads(data)
                if chunk.get('error'):
                    result['error'] = json.dumps(chunk['error'], ensure_ascii=False).replace(key, '[REDACTED]')
                    break
                if chunk.get('model'):
                    result['returned_model'] = chunk['model']
                if chunk.get('usage'):
                    result['usage'] = chunk['usage']
                for choice in chunk.get('choices', []):
                    if choice.get('finish_reason'):
                        result['finish_reason'] = choice['finish_reason']
                    delta = choice.get('delta', {})
                    reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
                    if isinstance(reasoning, str) and reasoning:
                        result.setdefault('first_reasoning_ms', now)
                        reasoning_chars += len(reasoning)
                    text = delta.get('content')
                    if not isinstance(text, str) or not text:
                        continue
                    result.setdefault('first_content_ms', now)
                    content += text
                    result['events'].append({'ms': now, 'text': text})
                    if len(content) >= 20:
                        result.setdefault('chars20_ms', now)
                    if re.search(r'[。！？!?；;]', content):
                        result.setdefault('first_sentence_ms', now)
                    # Separate proxy for Fay's 20-character-plus-punctuation buffer.
                    if len(content) >= 20 and re.search(r'[，,。！？!?；;：:]', content[11:]):
                        result.setdefault('tts_buffer_ms', now)
            result['ok'] = bool(content.strip() and result.get('finish_reason') == 'stop' and saw_done)
    except Exception as exc:
        result['error'] = (type(exc).__name__ + ': ' + str(exc)).replace(key, '[REDACTED]')[:2000]
    finally:
        result.update(total_ms=round((time.perf_counter() - start) * 1000, 2),
                      reply=content, reply_chars=len(content), reasoning_chars=reasoning_chars,
                      sse_done=saw_done)
    return result


def summarize(results):
    summary = {}
    for name in dict.fromkeys([case[0] for case in CASES] + [r['case'] for r in results]):
        rows = [r for r in results if r['case'] == name]
        good = [r for r in rows if r['ok']]
        stats = dict(attempts=len(rows), completed=len(good),
                     reasoning_observed=sum(r['reasoning_chars'] > 0 for r in good))
        for field in ('headers_ms', 'first_content_ms', 'chars20_ms', 'first_sentence_ms', 'tts_buffer_ms', 'total_ms'):
            values = [r[field] for r in good if field in r]
            if values:
                stats[field] = dict(median=round(statistics.median(values), 2), min=min(values), max=max(values))
        stats['reply_chars'] = [r['reply_chars'] for r in good]
        stats['reasoning_chars'] = [r['reasoning_chars'] for r in good]
        summary[name] = stats
    return summary


async def main(resume=None, probe_none=False):
    conf = FAY / 'system.conf'
    before = hashlib.sha256(conf.read_bytes()).hexdigest()
    saved = profile(read_config(conf), 'opencode_go')
    endpoint = saved.get('base_url', '').rstrip('/')
    if endpoint != PRESETS['opencode_go']['base_url'] or not saved.get('api_key'):
        raise SystemExit('Expected existing OpenCode Go profile unavailable; no request made.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = ROOT / 'docs' / ('go-flash-benchmark-' + stamp + '.json')
    report = dict(started_utc=stamp, endpoint=endpoint, system_prompt=SYSTEM,
                  scope='Direct streaming LLM only; no ASR, Fay orchestration, TTS or RTC',
                  schedule='Five paired rounds; sequential calls; rotated case order; fresh conversation per round shared across cases',
                  retries=0, request_count_limit=15, results=[])
    if resume:
        output = Path(resume).resolve()
        report = json.loads(output.read_text(encoding='utf-8'))
        report.pop('stopped_early', None)
        report['schedule'] = 'Five paired low rounds, rotated order; initial rejected Qwen enable_thinking=false; up to four explicit compatibility probes within 15 total attempts.'
        report['compatibility_note'] = 'MiMo native reasoning is binary. Gateway acceptance of low does not establish graded effort. Qwen low+enable_thinking=false returned HTTP 400, so low+thinking.type=disabled is probed separately.'
    def save():
        report['summary'] = summarize(report['results'])
        report['production_config_unchanged'] = hashlib.sha256(conf.read_bytes()).hexdigest() == before
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    timeout = ClientTimeout(total=75, connect=15, sock_read=45)
    async with ClientSession(timeout=timeout, trust_env=False) as client:
        for index, question in enumerate(PROMPTS):
            session = 'flash-benchmark-' + uuid.uuid4().hex
            ordered = CASES[index % 3:] + CASES[:index % 3]
            for case in ordered:
                if resume and (case[0] == 'qwen-low-off' or any(r['case'] == case[0] and r['round'] == index + 1 for r in report['results'])):
                    continue
                result = await probe(client, endpoint, saved['api_key'], case, question, index + 1, session)
                report['results'].append(result)
                save()
                print(json.dumps({k: result.get(k) for k in ('case', 'round', 'ok', 'http_status', 'first_content_ms', 'tts_buffer_ms', 'total_ms', 'reasoning_chars', 'finish_reason')}, ensure_ascii=True), flush=True)
                # A model/parameter rejection should not be retried on every subsequent round.
                if result.get('http_status') in (400, 401, 402, 403, 404, 429) or result.get('error'):
                    report['stopped_early'] = 'Inspect rejection or transport failure before spending further requests.'
                    save()
                    print(str(output), flush=True)
                    return
        if resume:
            off_case = ('qwen-low-off-compatible', 'qwen3.8-flash', {'reasoning_effort': 'low', 'thinking': {'type': 'disabled'}})
            if probe_none:
                off_case = ('qwen-off-none', 'qwen3.8-flash', {'reasoning_effort': 'none'})
                report['compatibility_note'] += ' Both low+off spellings returned 400. Remaining attempts test effort=none separately; this is NOT a low-effort result.'
            for index in range(4):
                if len(report['results']) >= 15:
                    break
                result = await probe(client, endpoint, saved['api_key'], off_case, PROMPTS[index], index + 1, 'flash-off-' + uuid.uuid4().hex)
                report['results'].append(result)
                save()
                print(json.dumps({k: result.get(k) for k in ('case', 'round', 'ok', 'http_status', 'first_content_ms', 'tts_buffer_ms', 'total_ms', 'reasoning_chars')}, ensure_ascii=True), flush=True)
                if not result['ok']:
                    break
    save()
    print(json.dumps(report['summary'], ensure_ascii=True), flush=True)
    print(str(output), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--probe-none', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.resume, args.probe_none))
