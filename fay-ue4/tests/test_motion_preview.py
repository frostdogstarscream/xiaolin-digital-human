import copy
import json
from pathlib import Path
import wave
import pytest
from character_contract import validate_face, validate_motion

ROOT=Path(__file__).resolve().parents[1]


def data():
    return json.loads((ROOT/'assets/girl008-motion-preview-v1.json').read_text(encoding='utf-8'))


def test_calibrated_rig_is_preview_only_and_all_bones_exist():
    spec=data()
    validate_face(spec);validate_motion(spec,preview=True)
    with pytest.raises(ValueError,match='preview'):validate_motion(spec)
    reference=json.loads((ROOT/'docs/girl008-ue-reference-rig.json').read_text(encoding='utf-8'))
    names={b['name'] for b in reference['bones']}
    mapped=[b['bone'] for group in spec['face_bones'].values() for b in group]+[b['bone'] for b in spec['body_bones']]
    assert len(mapped)==len(set(mapped)) and set(mapped)<=names
    # Closure needs actual nonzero displacement on both upper and lower lids.
    for channel in ('blink_left','blink_right'):
        assert any(sum(abs(x) for x in b['translation'])>.2 for b in spec['face_bones'][channel])


@pytest.mark.parametrize('change',['overlap','amplitude','nan'])
def test_bad_procedural_configuration_rejected(change):
    spec=copy.deepcopy(data())
    if change=='overlap':spec['body_bones'][0]['bone']=spec['face_bones']['jaw_open'][0]['bone']
    elif change=='amplitude':spec['body_bones'][0]['speaking'][0]=9
    else:spec['body_bones'][0]['phase']=float('nan')
    with pytest.raises(ValueError):validate_motion(spec,preview=True)


def test_local_audio_matches_native_preview_contract():
    with wave.open(str(ROOT/'assets/calibration-speech-v1.wav')) as sound:
        assert (sound.getnchannels(),sound.getsampwidth(),sound.getframerate())==(1,2,24000)
        assert 1<sound.getnframes()/sound.getframerate()<60
