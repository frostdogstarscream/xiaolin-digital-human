import copy
import json
import math
from pathlib import Path
import sys
import pytest
from character_contract import validate_face,validate_motion

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_girl008_actions import RIG,DEFINITIONS,pose
from calibrate_girl008 import add,sub,dot,mul,rotate


def spec():return json.loads((ROOT/'assets/girl008-actions-preview-v2.json').read_text(encoding='utf-8'))


def forward(pose_data):
    result={}
    for bone in RIG:
        q,p=result.get(bone['parent'],([0,0,0,1],[0,0,0]))
        key=pose_data.get(bone['name'],{'rotation':[0,0,0,1],'translation':[0,0,0]})
        result[bone['name']]=(mul(q,mul(bone['local_rotation'],key['rotation'])),add(p,rotate(q,add(bone['local_position'],key['translation']))))
    return result


def test_all_requested_actions_are_valid_and_target_real_body_bones():
    s=spec();validate_face(s);validate_motion(s,preview=True)
    assert set(s['motion_clips'])==set(DEFINITIONS)
    names={b['name'] for b in RIG}
    for c in s['motion_clips'].values():assert set(c['tracks'])<=names
    with pytest.raises(ValueError,match='preview'):validate_motion(s)


@pytest.mark.parametrize('name',list(DEFINITIONS))
def test_sampled_animation_is_finite_and_preserves_bone_lengths(name):
    duration,_=DEFINITIONS[name]
    reference={b['name']:math.sqrt(dot(b['local_position'],b['local_position'])) for b in RIG}
    for i in range(61):
        result=forward(pose(name,duration*i/60,duration))
        for b in RIG:
            q,p=result[b['name']]
            assert all(math.isfinite(v) for v in q+p)
            assert abs(dot(q,q)-1)<.0001
            if b['parent'] and b['name']!='Root_M':
                delta=sub(p,result[b['parent']][1]);assert abs(math.sqrt(dot(delta,delta))-reference[b['name']])<.001


def test_wave_raises_hand_and_nod_bow_move_head():
    neutral=forward(pose('wave',0,4))
    assert forward(pose('wave',1.4,4))['Wrist_R'][1][2]>neutral['Wrist_R'][1][2]+45
    assert forward(pose('bow',2,4))['Head_M'][1][1]>neutral['Head_M'][1][1]+15


def test_walking_feet_remain_above_ground_and_move():
    samples=[forward(pose('walk',5.6*i/112,5.6)) for i in range(113)]
    for side in ['L','R']:
        assert min(s['ToesEnd_'+side][1][2] for s in samples)>-.1
        assert max(s['Ankle_'+side][1][2] for s in samples)-min(s['Ankle_'+side][1][2] for s in samples)>2


def test_gestures_return_to_neutral_and_loops_join_without_jumps():
    for name,(duration,loop) in DEFINITIONS.items():
        a=pose(name,0,duration);b=pose(name,duration,duration)
        for n in a:
            assert abs(abs(dot(a[n]['rotation'],b[n]['rotation']))-1)<.00001
            assert max(abs(x-y) for x,y in zip(a[n]['translation'],b[n]['translation']))<.00001


@pytest.mark.parametrize('bad',['nan','time','quaternion','face','oversize'])
def test_malformed_clips_are_rejected(bad):
    s=copy.deepcopy(spec());c=s['motion_clips']['wave'];track=next(iter(c['tracks'].values()))
    if bad=='nan':track[1]['translation'][0]=float('nan')
    if bad=='time':track[1]['time']=0
    if bad=='quaternion':track[1]['rotation']=[0,0,0,0]
    if bad=='face':c['tracks']['JawJoint_M']=track
    if bad=='oversize':c['duration']=100
    with pytest.raises(ValueError):validate_motion(s,preview=True)
