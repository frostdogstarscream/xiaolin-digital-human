"""Shared stdlib-only character validation (also runs in UE4's Python 3.7)."""
import math
import re

CHANNELS = ('jaw_open', 'blink_left', 'blink_right')


def validate_face(spec):
    mode = spec.get('face_driver', 'morph')
    if mode == 'morph':
        if not all(spec.get('morphs', {}).get(k) for k in CHANNELS):
            raise ValueError('Jaw and blink mappings are required')
    elif mode == 'bones':
        channels = spec.get('face_bones', {})
        if set(channels) != set(CHANNELS):
            raise ValueError('Bone driver requires jaw_open, blink_left and blink_right')
        used = set()
        for channel in CHANNELS:
            bindings = channels[channel]
            if not isinstance(bindings, list) or not 1 <= len(bindings) <= 64:
                raise ValueError('Each face channel needs 1..64 bone bindings')
            for binding in bindings:
                if not isinstance(binding, dict) or set(binding) != {'bone', 'rotation', 'translation'}:
                    raise ValueError('Bone binding needs bone, rotation and translation')
                name = binding['bone']
                if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,128}', name) or name in used:
                    raise ValueError('Invalid or duplicate face bone')
                used.add(name)
                for field, limit in (('rotation', 45), ('translation', 5)):
                    values = binding[field]
                    if not isinstance(values, list) or len(values) != 3 or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > limit for v in values
                    ):
                        raise ValueError('Invalid bone ' + field)
    else:
        raise ValueError('Unknown face_driver')


def validate_motion(spec, field='animations', preview=False):
    if 'motion_clips' in spec:
        if not preview or spec.get('motion_mode') != 'procedural': raise ValueError('Keyframe clips are preview-only')
        validate_clips(spec)
    mode = spec.get('motion_mode', 'animations')
    if mode in ('reference_pose', 'procedural'):
        if not preview:
            raise ValueError(mode + ' is only allowed in an isolated preview')
        if spec.get(field):
            raise ValueError(mode + ' must not contain animation assets')
        if mode == 'procedural':
            if spec.get('face_driver') != 'bones': raise ValueError('Procedural preview requires bone face driver')
            bindings=spec.get('body_bones', [])
            if not isinstance(bindings,list) or not 1 <= len(bindings) <= 32: raise ValueError('Invalid body_bones')
            used={b['bone'] for values in spec.get('face_bones',{}).values() for b in values}
            for b in bindings:
                if set(b) != {'bone','rotation','idle','speaking','phase'} or b['bone'] in used: raise ValueError('Invalid/overlapping body bone')
                used.add(b['bone'])
                for field_name,limit in (('rotation',120),('idle',3),('speaking',8)):
                    values=b[field_name]
                    if not isinstance(values,list) or len(values)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>limit for x in values): raise ValueError('Invalid body '+field_name)
                if isinstance(b['phase'],bool) or not isinstance(b['phase'],(int,float)) or not math.isfinite(b['phase']) or abs(b['phase'])>10: raise ValueError('Invalid body phase')
    elif mode == 'animations':
        if not all(spec.get(field, {}).get(k) for k in ('idle', 'speaking')):
            raise ValueError('Idle and speaking animations are required')
    else:
        raise ValueError('Unknown motion_mode')


def validate_clips(spec):
    clips=spec['motion_clips']
    if not isinstance(clips,dict) or not 1 <= len(clips) <= 16 or 'idle' not in clips: raise ValueError('Invalid motion library')
    face={b['bone'] for group in spec['face_bones'].values() for b in group}
    for name,clip in clips.items():
        if not re.fullmatch('[a-z_]{1,32}',name): raise ValueError('Invalid clip name')
        duration=clip.get('duration')
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not .5 <= duration <= 30 or not isinstance(clip.get('loop'),bool): raise ValueError('Invalid clip duration/loop')
        tracks=clip.get('tracks')
        if not isinstance(tracks,dict) or not 1 <= len(tracks) <= 32: raise ValueError('Invalid motion tracks')
        for bone,keys in tracks.items():
            if bone in face or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,128}',bone): raise ValueError('Invalid/face motion bone')
            if not isinstance(keys,list) or not 2 <= len(keys) <= 512: raise ValueError('Invalid motion keys')
            previous=-1
            for key in keys:
                t=key.get('time')
                if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or not previous < t <= duration: raise ValueError('Invalid motion key time')
                previous=t
                for field,count,limit in [('rotation',4,1.001),('translation',3,60)]:
                    a=key.get(field)
                    if not isinstance(a,list) or len(a)!=count or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>limit for x in a): raise ValueError('Invalid motion key transform')
                if abs(sum(x*x for x in key['rotation'])-1)>.002: raise ValueError('Motion quaternion is not normalized')
            if keys[0]['time']!=0 or abs(keys[-1]['time']-duration)>.001: raise ValueError('Motion keys must span clip')
