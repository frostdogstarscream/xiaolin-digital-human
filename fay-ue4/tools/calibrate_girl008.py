"""Derive conservative preview deltas from UE's actual reference skeleton.

Outputs a new JSON revision. These are calibration candidates, not artist-authored
animations; validate screenshots and local playback before promoting any values.
"""
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character_contract import validate_face, validate_motion


def add(a, b): return [x + y for x, y in zip(a, b)]
def sub(a, b): return [x - y for x, y in zip(a, b)]
def scale(a, v): return [x * v for x in a]
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def unit(a): return scale(a, 1 / math.sqrt(dot(a, a)))
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def inv(q): return [-q[0], -q[1], -q[2], q[3]]
def mul(a, b): return add(add(scale(b[:3], a[3]), scale(a[:3], b[3])), cross(a[:3], b[:3])) + [a[3]*b[3]-dot(a[:3], b[:3])]
def rotate(q, v): return mul(mul(q, v+[0]), inv(q))[:3]
def axis_angle(axis, angle): return scale(unit(axis), math.sin(math.radians(angle)/2)) + [math.cos(math.radians(angle)/2)]
def between(a, b):
    a, b = unit(a), unit(b)
    return unit(cross(a, b) + [1 + dot(a, b)])


def rotator(q):
    # UE4 FQuat::Rotator conventions, not a generic XYZ Euler conversion.
    x,y,z,w = unit(q)
    singular = z*x-w*y
    yaw = math.degrees(math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z)))
    if abs(singular) > .4999995:
        pitch = 90 if singular > 0 else -90
        roll = (yaw if singular > 0 else -yaw) - math.degrees(2*math.atan2(x,w))
    else:
        pitch = math.degrees(math.asin(2*singular))
        roll = math.degrees(math.atan2(-2*(w*x+y*z),1-2*(x*x+y*y)))
    return [round(pitch,6), round(yaw,6), round((roll+180)%360-180,6)]


def local_delta(bone, component_rotation):
    q = bone['rotation']
    return mul(mul(inv(q),component_rotation),q)


def interpolate(points, x):
    points = sorted(points, key=lambda p:p[0])
    if x <= points[0][0]: return points[0]
    if x >= points[-1][0]: return points[-1]
    for a,b in zip(points, points[1:]):
        if a[0] <= x <= b[0]: return add(a,scale(sub(b,a),(x-a[0])/(b[0]-a[0])))
    raise ValueError('Cannot interpolate lid curve')


def generate():
    rig = json.loads((ROOT/'docs/girl008-ue-reference-rig.json').read_text(encoding='utf-8'))
    bones = {b['name']: b for b in rig['bones']}
    spec = json.loads((ROOT/'ue4/Saved/girl008_preview_v1-preview.json').read_text(encoding='utf-8'))
    spec.update(id='girl008_motion_preview_v1', name='girl008 本地动作预览', motion_mode='procedural',
                preview_audio='../assets/calibration-speech-v1.wav', preview_jaw=0, preview_blink=-1,
                preview_camera_distance=350, preview_camera_height=90, preview_autoplay=False)
    # Resolve audio relative to project directory in C++ to keep the manifest portable.
    body = []
    def body_binding(name, base=None, idle_axis=(1,0,0), idle=0.3, talk=1, phase=0):
        b=bones[name]
        body.append(dict(bone=name,rotation=rotator(base or [0,0,0,1]),
                         idle=rotator(local_delta(b,axis_angle(list(idle_axis),idle))),
                         speaking=rotator(local_delta(b,axis_angle(list(idle_axis),talk))),phase=phase))
    for side,sign in [('L',1),('R',-1)]:
        name='Shoulder_'+side;b=bones[name]
        direction=sub(bones['Elbow_'+side]['position'],b['position'])
        target=[sign*.24,.08,-.967]
        component=between(direction,target)
        assert dot(unit(rotate(component,direction)),unit(target)) > .99999
        body_binding(name,local_delta(b,component),idle_axis=(0,1,0),idle=.25,talk=2.2,phase=0 if side=='L' else 1.7)
    body_binding('Spine1_M',idle=.25,talk=.6,phase=.5)
    body_binding('Chest_M',idle=.35,talk=.75,phase=0)
    body_binding('Head_M',idle=.25,talk=1.2,phase=1.1)
    spec['body_bones']=body

    channels={'jaw_open':[], 'blink_left':[], 'blink_right':[]}
    for side,channel in [('L','blink_left'),('R','blink_right')]:
        upper=[b for n,b in bones.items() if n.startswith('upperLidMain') and n.endswith('_'+side)]
        lower=[b for n,b in bones.items() if n.startswith('lowerLidMain') and n.endswith('_'+side)]
        up=[b['position'] for b in upper];lo=[b['position'] for b in lower]
        xmin=min(p[0] for p in up);xmax=max(p[0] for p in up)
        for b in upper+lower:
            p=b['position'];u=interpolate(up,p[0]);l=interpolate(lo,p[0])
            arc=math.sin(math.pi*(p[0]-xmin)/(xmax-xmin))
            target=[p[0],max(u[1],l[1])+.08*max(0,arc),.22*u[2]+.78*l[2]]
            delta=rotate(inv(b['rotation']),sub(target,p))
            channels[channel].append(dict(bone=b['name'],rotation=[0,0,0],translation=[round(x,6) for x in delta]))

    pivot=bones['JawJoint_M']['position']
    opening=axis_angle([1,0,0],-6)
    for name,b in bones.items():
        if name not in ('JawJoint_M','lowerTeethJoint_M','Tongue0Joint_M') and not name.startswith(('lowerLipJoint','upperLipJoint')): continue
        p=b['position'];weight=max(.08,1-(abs(p[0])/2.3)**2)
        rotation=[0,0,0];delta=[0,0,0]
        if name=='JawJoint_M': rotation=rotator(local_delta(b,opening))
        elif name.startswith('upperLipJoint'): delta=[0,0,.06*weight]
        else:
            target=add(pivot,rotate(opening,sub(p,pivot)))
            delta=sub(target,p)
            if name.startswith('lowerLipJoint'): delta=scale(delta,weight)
            else: rotation=rotator(local_delta(b,opening))
        # Runtime translation uses the post-rotation local basis.
        q=mul(b['rotation'],local_delta(b,opening)) if name in ('lowerTeethJoint_M','Tongue0Joint_M') else b['rotation']
        channels['jaw_open'].append(dict(bone=name,rotation=rotation,translation=[round(x,6) for x in rotate(inv(q),delta)]))
    spec['face_bones']=channels
    validate_face(spec);validate_motion(spec,preview=True)
    path=ROOT/'assets/girl008-motion-preview-v1.json'
    if path.exists(): raise FileExistsError('Retain existing calibration; use a new revision')
    path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved',path,'face bones',sum(len(v) for v in channels.values()),'body bones',len(body))


if __name__=='__main__':generate()
