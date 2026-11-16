"""Activate native dual roles using the already-authorized saved primary model."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))
import provider_config
from bailian_speech import settings as speech_settings


def main():
    before=provider_config.read_config()
    old_tts=speech_settings()
    public=provider_config.set_collaboration('dual_primary_placeholder')
    after=provider_config.read_config()
    changed=[]
    for section in before.sections():
        for key,value in before[section].items():
            if after[section].get(key)!=value:
                assert section=='key' and key in ('big_model_engine','big_model_base_url','big_model_api_key')
                changed.append(key)
    assert speech_settings()==old_tts
    assert public['collaboration']['mode']=='dual'
    report=dict(provider=public,tts_unchanged=True,unrelated_existing_settings_unchanged=True,
                placeholder_model=public['model'],credentials_returned=False)
    (ROOT/'docs/collaboration-activation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'mode':public['collaboration']['mode'],'primary':public['model'],
        'background':public['collaboration']['big_model'],'same_model_placeholder':True,'tts_unchanged':True},ensure_ascii=True))


if __name__=='__main__':main()
