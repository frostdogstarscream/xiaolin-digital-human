"""Six sequential real Fay/TTS/RTC trials; restore only scoped small-role configuration."""
import asyncio
import argparse
import contextlib
import hashlib
import io
import json
import statistics
import sys
from datetime import datetime, timezone

from aiohttp import ClientSession, ClientTimeout

import benchmark_go_flash as probe
import check_go_dialogue as dialogue

provider=sys.modules['provider_config']
ROOT=probe.ROOT


async def main(resume=None):
    conf=provider.FAY/'system.conf'
    original=provider.read_config()
    original_sections={s:dict(original[s]) for s in original.sections()}
    original_hash=hashlib.sha256(conf.read_bytes()).hexdigest()
    previous_model=original['key']['gpt_model_engine']
    original_small=dict(original['llm_generation:small']) if 'llm_generation:small' in original else None
    saved=provider.profile(original,'opencode_go')
    assert provider.active_provider(original)=='opencode_go'
    assert saved['base_url']==provider.PRESETS['opencode_go']['base_url']
    assert previous_model=='deepseek-v4.1-flash'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=ROOT/'docs'/f'fay-live-flash-comparison-{stamp}.json'
    report=dict(started_utc=stamp,question=dialogue.QUESTION,trials=[],preflight=[],
        design='Two warm-service trials per model; Qwen/MiMo/DeepSeek then reverse order; sequential requests; same live history policy; history retained and naturally appended, not frozen.',
        scope='Existing Fay, streaming Bailian TTS and RTC display; no restart, new RTC offer, owner claim or database edits.',
        restored=False,original_config_sha256=original_hash)
    if resume:
        output=resume.resolve()
        previous=output.read_text(encoding='utf-8')
        snapshot=output.with_name(output.stem+'-before-resume.json')
        assert not snapshot.exists(),'Resume snapshot already exists'
        snapshot.write_text(previous,encoding='utf-8')
        report=json.loads(previous)
        report['previous_run_error']=report.pop('error',None)
        report['resumed_after']='File audio/cache hit was rejected by the prior streaming-only observer; now retain transport labels and exclude file rows from TTS streaming stats.'
        stamp=report['started_utc']
    last_model=None;last_generation=None
    def save():
        text=json.dumps(report,ensure_ascii=False,indent=2)
        assert saved['api_key'] not in text
        output.write_text(text,encoding='utf-8')
    def switch(model):
        nonlocal last_model,last_generation
        current=provider.read_config()
        assert current['key']['gpt_model_engine']==(last_model or previous_model),'Another user changed model'
        generation=original_small if model==previous_model else dict(
            base_url=saved['base_url'],model=model,reasoning_effort='none')
        current['key']['gpt_model_engine']=model
        current['llm_generation:small']=generation
        provider.write_config(current)
        last_model=model;last_generation=dict(generation)
    async with ClientSession(trust_env=False,timeout=ClientTimeout(total=75,connect=15,sock_read=45)) as http:
        async with http.get(dialogue.BASE+'/api/health') as response:
            health=await response.json()
        assert health['rtc_connected'] and health['fay_core'] and health['model_state']=='ready'
        assert not any(j['status'] in ('queued','streaming','rendering','preparing') for j in health['jobs'])
        report['display_session']=health['sessionid']
        save()
        try:
            print('Checking MiMo none compatibility; then up to six live dialogue trials.',flush=True)
            if not report['preflight']:
                result=await probe.probe(http,saved['base_url'],saved['api_key'],
                    ('mimo-off-none','mimo-v2.6-flash',{'reasoning_effort':'none'}),dialogue.QUESTION,1,'mimo-none-compat-'+stamp)
                report['preflight'].append(result);save()
            assert all(r['ok'] and r['reasoning_chars']==0 for r in report['preflight']),'MiMo none compatibility not verified; formal configuration left unchanged'
            print('MiMo none preflight passed, no visible reasoning.',flush=True)
            models=['qwen3.8-flash','mimo-v2.6-flash',previous_model,
                    previous_model,'mimo-v2.6-flash','qwen3.8-flash']
            for number,model in enumerate(models,1):
                if number<=len(report['trials']):
                    continue
                async with http.get(dialogue.BASE+'/api/health') as response:
                    health=await response.json()
                assert health['sessionid']==report['display_session']
                assert not any(j['status'] in ('queued','streaming','rendering','preparing') for j in health['jobs'])
                switch(model)
                filename=f'live-flash-{stamp}-{number}-{model}.json'
                with contextlib.redirect_stdout(io.StringIO()):
                    trial=await dialogue.main(filename,allow_file_audio=True)
                assert trial['model']==model
                assert trial['fay_trace']['meta']['route']=='direct' and trial['fay_trace']['meta']['tool_count']==0
                report['trials'].append(trial)
                save()
                print(json.dumps(dict(trial=number,model=model,first_model_content=trial['stage_seconds']['model_to_first_content'],
                    first_visible_text=trial['first_answer_text_seconds'],first_playback=trial['first_playback_callback_seconds'],
                    audio_path=trial.get('audio_path','streamed_pcm'),prompt_chars=trial['fay_trace']['meta']['prompt_chars']),ensure_ascii=True),flush=True)
        except Exception as exc:
            report['error']=(type(exc).__name__+': '+str(exc)).replace(saved['api_key'],'[REDACTED]')
            raise
        finally:
            current=provider.read_config()
            if last_model is not None:
                assert current['key']['gpt_model_engine']==last_model and dict(current['llm_generation:small'])==last_generation,'Concurrent config change; refusing to overwrite'
                current['key']['gpt_model_engine']=previous_model
                if original_small is None:current.remove_section('llm_generation:small')
                else:current['llm_generation:small']=original_small
                provider.write_config(current)
            final=provider.read_config()
            report['restored']={s:dict(final[s]) for s in final.sections()}==original_sections
            report['restored_config_sha256']=hashlib.sha256(conf.read_bytes()).hexdigest()
            report['exact_config_bytes_restored']=report['restored_config_sha256']==original_hash
            report['summary']={}
            for model in {t['model'] for t in report['trials']}:
                rows=[t for t in report['trials'] if t['model']==model]
                streamed=[t for t in rows if t.get('audio_path','streamed_pcm')=='streamed_pcm']
                report['summary'][model]=dict(samples=len(rows),
                    model_to_first_content_median=statistics.median(t['stage_seconds']['model_to_first_content'] for t in rows),
                    first_visible_text_median=statistics.median(t['first_answer_text_seconds'] for t in rows),
                    first_playback_median=statistics.median(t['first_playback_callback_seconds'] for t in rows),
                    first_playback_median_scope='All audio paths, including cache/file audio where marked',
                    streamed_first_playback_median=statistics.median(t['first_playback_callback_seconds'] for t in streamed) if streamed else None,
                    streamed_pcm_samples=sum(t.get('audio_path','streamed_pcm')=='streamed_pcm' for t in rows),
                    file_audio_samples=sum(t.get('audio_path')=='file_audio' for t in rows))
            save()
            print('Restored original DeepSeek role configuration:',report['restored'],flush=True)
            print(str(output),flush=True)
    assert report['restored']


if __name__=='__main__':
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--resume',type=Path);args=parser.parse_args()
    asyncio.run(main(args.resume))
