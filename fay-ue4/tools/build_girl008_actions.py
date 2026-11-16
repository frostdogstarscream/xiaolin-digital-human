"""Author sampled local quaternion tracks against the actual UE reference skeleton.

All output is a new preview revision. No source mesh or older calibration is edited.
Coordinates below are in imported mesh space: +Y forward, +Z up.
"""
import json
import math
from pathlib import Path
from calibrate_girl008 import add, sub, scale, dot, unit, cross, inv, mul, rotate, axis_angle, between

ROOT = Path(__file__).resolve().parents[1]
RIG = json.loads((ROOT/'docs/girl008-ue-reference-rig.json').read_text(encoding='utf-8'))['bones']
BONES = {b['name']: b for b in RIG}
IDENTITY = [0, 0, 0, 1]
TRACKS = ['Root_M','Spine1_M','Chest_M','Head_M'] + [n+'_'+s for s in ('L','R') for n in ('Shoulder','Elbow','Wrist','Hip','Knee','Ankle')]
TRACKS += [finger+str(i)+'_L' for finger in ('MiddleFinger','RingFinger','PinkyFinger') for i in (2,3)]


def smooth(x):
    x=max(0,min(1,x));return x*x*(3-2*x)


def envelope(t, duration, ramp=.7):
    return smooth(t/ramp)*smooth((duration-t)/ramp)


def align(name, child, direction):
    b=BONES[name]
    return mul(between(sub(BONES[child]['position'],b['position']),direction),b['rotation'])


def palm_normal(side):
    wrist=BONES['Wrist_'+side]['position']
    direction=unit(sub(BONES['MiddleFinger1_'+side]['position'],wrist))
    across=sub(BONES['IndexFinger1_'+side]['position'],BONES['PinkyFinger1_'+side]['position'])
    return scale(unit(cross(direction,across)),1 if side=='R' else -1)


def face_palm(q,side,direction,target,weight):
    axis=unit(direction)
    current=rotate(mul(q,inv(BONES['Wrist_'+side]['rotation'])),palm_normal(side))
    a=unit(sub(current,scale(axis,dot(current,axis))))
    b=unit(sub(target,scale(axis,dot(target,axis))))
    angle=math.degrees(math.atan2(dot(axis,cross(a,b)),dot(a,b)))
    return mul(axis_angle(axis,angle*weight),q)


def leg_targets(side, offset, root_offset):
    hip=BONES['Hip_'+side]['position']; knee=BONES['Knee_'+side]['position']; foot=BONES['Ankle_'+side]['position']
    h=add(hip,root_offset);a=add(foot,offset)
    upper=math.sqrt(dot(sub(knee,hip),sub(knee,hip)));lower=math.sqrt(dot(sub(foot,knee),sub(foot,knee)))
    d=sub(a,h);dist=math.sqrt(dot(d,d));v=unit(d)
    if not abs(upper-lower)<dist<upper+lower: raise ValueError('Unreachable foot target')
    along=(upper*upper-lower*lower+dist*dist)/(2*dist)
    bend=unit(sub([0,1,0],scale(v,dot([0,1,0],v))))
    k=add(add(h,scale(v,along)),scale(bend,math.sqrt(max(0,upper*upper-along*along))))
    return {'Hip_'+side:align('Hip_'+side,'Knee_'+side,sub(k,h)),
            'Knee_'+side:align('Knee_'+side,'Ankle_'+side,sub(a,k)),
            'Ankle_'+side:BONES['Ankle_'+side]['rotation']}


def pose(action,t,duration):
    w=envelope(t,duration);angles={};targets={};root=[0,0,0]
    # Default stance: relaxed arms with slight elbow bend.
    arms={s:([sign*.24,.08,-.967],[sign*.19,.12,-.975]) for s,sign in [('L',1),('R',-1)]}
    if action in ('idle','speaking'):
        w=1; phase=2*math.pi*t/duration
        angles={'Spine1_M':([0,1,0],.6*math.sin(phase)), 'Chest_M':([1,0,0],.5*math.sin(phase)),
                'Head_M':([0,0,1],2.5*math.sin(phase))}
        if action=='speaking':
            arms['R']=([-.42,.16+.035*math.sin(phase),-.89],[-.38,.65+.10*math.sin(phase),-.55+.07*math.sin(phase)])
            angles['Head_M']=([1,0,0],1.8*math.sin(phase*2))
    if action in ('wave','welcome','goodbye'):
        swing=math.sin(2*math.pi*1.25*(t-.7))*w
        arms['R']=([-.24-.32*w,.08+.12*w,-.967+.30*w],[-.19+.39*w+.23*swing,.12+.12*w,-.975+1.94*w])
        angles['Head_M']=([0,1,0],-3*w)
    if action=='explain':
        oscillation=.07*math.sin(t*2*math.pi/.95)*w
        arms['R']=([-.24-.32*w,.08+.16*w,-.967+.25*w],[-.19-.40*w,.12+.64*w,-.975+.93*w+oscillation])
        arms['L']=([.24+.10*w,.08+.05*w,-.967+.03*w],[.19+.15*w,.12+.32*w,-.975+.25*w])
        angles['Head_M']=([1,0,0],-2*w*math.sin(t*3))
    if action=='point':
        arms['L']=([.24+.55*w,.08+.40*w,-.967+.80*w],[.19+.58*w,.12+.44*w,-.975+.90*w])
        angles['Head_M']=([0,0,1],-10*w)
    if action=='nod':angles['Head_M']=([1,0,0],-11*w*(.5-.5*math.cos(t*2*math.pi/1.1)))
    if action=='bow':
        angles={'Spine1_M':([1,0,0],-16*w),'Chest_M':([1,0,0],-9*w),'Head_M':([1,0,0],-6*w)}
    if action in ('turn_left','turn_right'):
        angles['Root_M']=([0,0,1],(75 if action=='turn_left' else -75)*w)
        # IK foot pivoting is authored below as a whole-body turn, returning to front.
    if action=='walk':
        # Two short cycles, with an analytic two-bone solve and level ankles.
        phase=2*math.pi*t/1.4;root=[.65*w*math.sin(phase),0,-.8*w]
        for s,sign in [('L',1),('R',-1)]:
            p=phase+(0 if s=='L' else math.pi)
            offset=[0,9*w*math.cos(p),3.5*w*max(0,math.sin(p))]
            targets.update(leg_targets(s,offset,root))
            swing=math.sin(p)*w
            arms[s]=([sign*.24,.08+.16*swing,-.967],[sign*.19,.12+.18*swing,-.975])
        angles['Chest_M']=([0,0,1],2*w*math.sin(phase))
    whole=axis_angle([0,0,1],(75 if action=='turn_left' else -75)*w) if action.startswith('turn_') else IDENTITY
    torso=axis_angle([1,0,0],-25*w) if action=='bow' else IDENTITY
    for side,(upper,fore) in arms.items():
        shoulder=align('Shoulder_'+side,'Elbow_'+side,upper)
        elbow=align('Elbow_'+side,'Wrist_'+side,fore)
        wrist=mul(mul(elbow,inv(BONES['Elbow_'+side]['rotation'])),BONES['Wrist_'+side]['rotation'])
        if action in ('wave','welcome','goodbye') and side=='R':
            wrist=face_palm(wrist,side,fore,[0,1,0],w)
            wrist=mul(axis_angle([0,1,0],12*w*math.sin((t-.7)*2*math.pi*1.25)),wrist)
        if action=='explain' and side=='R':wrist=face_palm(wrist,side,fore,[0,0,1],w)
        for n,q in [('Shoulder',shoulder),('Elbow',elbow),('Wrist',wrist)]:targets[n+'_'+side]=mul(whole,mul(torso,q))
    # Build component hierarchy, then express each authored rotation as local delta.
    current={};result={}
    for b in RIG:
        n=b['name'];parent=current.get(b['parent'],IDENTITY)
        inherited=mul(parent,b['local_rotation'])
        q=targets.get(n,inherited)
        if n in angles:q=mul(axis_angle(*angles[n]),inherited)
        if action=='point' and n in TRACKS and 'Finger' in n:
            # Fold the other three fingers toward the palm while keeping index extended.
            local_axis=rotate(inv(b['rotation']),cross([1,0,0],palm_normal('L')))
            q=mul(inherited,axis_angle(local_axis,48*w))
        current[n]=q
        if n in TRACKS:
            delta=unit(mul(inv(b['local_rotation']),mul(inv(parent),q)))
            translation=rotate(inv(parent),root) if n=='Root_M' else [0,0,0]
            result[n]={'rotation':[round(x,8) for x in delta],'translation':[round(x,6) for x in translation]}
    return result


DEFINITIONS={'idle':(8,True),'speaking':(4,True),'wave':(4,False),'welcome':(4,False),
             'goodbye':(4,False),'explain':(5,False),'nod':(3,False),'bow':(4,False),
             'point':(4,False),'walk':(5.6,True),'turn_left':(4,False),'turn_right':(4,False)}


def generate():
    spec=json.loads((ROOT/'assets/girl008-motion-preview-v1.json').read_text(encoding='utf-8'))
    spec.update(id='girl008_actions_preview_v2',name='girl008 动作集预览',motion_clips={})
    for name,(duration,loop) in DEFINITIONS.items():
        tracks={n:[] for n in TRACKS};count=round(duration*20)
        for i in range(count+1):
            t=duration*i/count
            for n,value in pose(name,t,duration).items():tracks[n].append(dict(time=round(t,6),**value))
        spec['motion_clips'][name]=dict(duration=duration,loop=loop,tracks=tracks)
    from character_contract import validate_face,validate_motion
    validate_face(spec);validate_motion(spec,preview=True)
    out=ROOT/'assets/girl008-actions-preview-v2.json'
    out.write_text(json.dumps(spec,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    print('Authored',len(DEFINITIONS),'clips;',len(TRACKS),'tracks per clip;',out)


if __name__=='__main__':generate()
