"""Compare DeepSeek low, none, and explicit disabled+low without production writes."""
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone

from aiohttp import ClientSession, ClientTimeout

import benchmark_go_flash as bench


async def main():
    cases = [
        ('deepseek-low', 'deepseek-v4.1-flash', {'reasoning_effort': 'low'}),
        ('deepseek-off-none', 'deepseek-v4.1-flash', {'reasoning_effort': 'none'}),
        ('deepseek-off-low', 'deepseek-v4.1-flash',
         {'reasoning_effort': 'low', 'thinking': {'type': 'disabled'}}),
    ]
    bench.CASES = cases
    conf = bench.FAY / 'system.conf'
    before = hashlib.sha256(conf.read_bytes()).hexdigest()
    saved = bench.profile(bench.read_config(conf), 'opencode_go')
    endpoint = saved.get('base_url', '').rstrip('/')
    if endpoint != bench.PRESETS['opencode_go']['base_url'] or not saved.get('api_key'):
        raise SystemExit('Expected existing Go profile unavailable; no request made.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = bench.ROOT / 'docs' / ('go-deepseek-flash-benchmark-' + stamp + '.json')
    report = dict(started_utc=stamp, endpoint=endpoint, system_prompt=bench.SYSTEM,
                  scope='Direct streaming LLM; no ASR, Fay orchestration, TTS or RTC',
                  schedule='Five identical questions from previous Flash benchmark; sequential calls; rotated case order; fresh session each round shared by cases',
                  max_requests=15, retries=0, config_sha256_before=before, results=[], rejected_cases=[])

    def save():
        report['summary'] = bench.summarize(report['results'])
        report['config_sha256_after'] = hashlib.sha256(conf.read_bytes()).hexdigest()
        report['production_config_unchanged'] = report['config_sha256_after'] == before
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        assert saved['api_key'] not in serialized, 'Unexpected credential in report'
        output.write_text(serialized, encoding='utf-8')

    save()
    print('START: up to 15 DeepSeek streaming requests; existing config read-only.', flush=True)
    async with ClientSession(timeout=ClientTimeout(total=75, connect=15, sock_read=45), trust_env=False) as client:
        for index, question in enumerate(bench.PROMPTS):
            session = 'deepseek-benchmark-' + uuid.uuid4().hex
            order = cases[index % 3:] + cases[:index % 3]
            for case in order:
                if case[0] in report['rejected_cases']:
                    continue
                assert len(report['results']) < 15
                result = await bench.probe(client, endpoint, saved['api_key'], case, question, index + 1, session)
                report['results'].append(result)
                if not result['ok']:
                    report['rejected_cases'].append(case[0])
                save()
                print(json.dumps({k: result.get(k) for k in ('case', 'round', 'ok', 'http_status', 'first_content_ms', 'first_sentence_ms', 'total_ms', 'reasoning_chars', 'finish_reason')}, ensure_ascii=True), flush=True)
                if result.get('http_status') in (401, 402, 403, 429):
                    report['stopped_early'] = 'Authentication, permission or allowance rejection; no further requests.'
                    save()
                    print(str(output), flush=True)
                    return
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(report['summary'], ensure_ascii=True), flush=True)
    print(str(output), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
