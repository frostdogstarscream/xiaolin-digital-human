"""Use each gesture's own neutral frames for review pauses to avoid body-size jumps."""
import json
from pathlib import Path

import cv2
import numpy as np

from prepare_motion_library import ROOT, LIB, encode, foreground_box, save


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def collect(path, indices):
    cap=cv2.VideoCapture(str(path))
    result={}
    index=0
    while True:
        ok,frame=cap.read()
        if not ok:
            break
        if index in indices:
            result[index]=frame
        index+=1
    fps=cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if set(result)!=set(indices):
        raise RuntimeError('Missing inspection frames')
    return result,index,fps


def main():
    library=read(LIB/'action-library.json')
    directory=ROOT/'outputs/motion-review-v3'
    directory.mkdir(exist_ok=False)
    intermediate=directory/'sequence-intermediate.mp4'
    writer=cv2.VideoWriter(str(intermediate),cv2.VideoWriter_fourcc(*'mp4v'),25,(720,1280))
    if not writer.isOpened():
        raise RuntimeError('Could not open review encoder')
    timeline=[]
    cursor=0
    def append_pause(frame, source_action, source_frame):
        nonlocal cursor
        start=cursor
        for _ in range(25):
            writer.write(frame)
            cursor+=1
        timeline.append(dict(action='neutral-pause',source_action=source_action,
                             source_frame=source_frame,start_frame=start,
                             end_frame_exclusive=cursor,start_seconds=start/25,end_seconds=cursor/25))
    for i,key in enumerate(['welcome-wave','explain-open-palms','acknowledge-nod','goodbye-wave']):
        action=next(a for a in library['actions'] if a['id']==key)
        cap=cv2.VideoCapture(str(ROOT/action['video']))
        ok,frame=cap.read()
        if not ok:
            raise RuntimeError('Cannot read gesture: '+key)
        if i==0:
            append_pause(frame,key,0)
        start=cursor
        count=0
        while ok:
            writer.write(frame)
            last=frame
            count+=1
            cursor+=1
            ok,frame=cap.read()
        cap.release()
        if count!=action['frames']:
            raise RuntimeError('Gesture frame count mismatch: '+key)
        timeline.append(dict(action=key,start_frame=start,end_frame_exclusive=cursor,
                             start_seconds=start/25,end_seconds=cursor/25))
        append_pause(last,key,count-1)
    writer.release()
    target=directory/'motion-sequence.mp4'
    encode(intermediate,target)
    indices=[0,12,24,25,37,50,75,100,199,200,224,225,449,450,475,574,575,600,774,775,799]
    new,count,fps=collect(target,indices)
    old,old_count,_=collect(ROOT/'outputs/motion-review-v2/motion-sequence.mp4',indices)
    if count!=800 or old_count!=800 or abs(fps-25)>.001:
        raise RuntimeError('Unexpected sequence duration or frame rate')
    measurements=[]
    for version,frames in [('v2',old),('v3',new)]:
        for index in [0,12,24,25,37,50]:
            box=foreground_box(frames[index])
            measurements.append(dict(version=version,frame=index,seconds=index/25,
                                     foreground_bbox=list(box)))
    # At the opening pause-to-gesture join, pose and scale should be the same decoded source frame.
    before=float(np.abs(old[24].astype(np.float32)-old[25]).mean())
    after=float(np.abs(new[24].astype(np.float32)-new[25]).mean())
    if after>1.0 or after>=before:
        raise RuntimeError(f'Opening pose continuity check failed: {before} -> {after}')
    rows=[]
    for version,frames in [('v2',old),('v3',new)]:
        tiles=[]
        for index in [0,12,25,50]:
            tile=cv2.resize(frames[index],(180,320))
            cv2.putText(tile,f'{version} / {index/25:.2f}s',(5,20),
                        cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
            tiles.append(tile)
        rows.append(np.hstack(tiles))
    save(directory/'opening-before-after.jpg',np.vstack(rows))
    report=dict(status='MEDIA_AND_OPENING_CONTINUITY_CHECK_PASSED',frames=count,fps=25,
                width=720,height=1280,seconds=count/25,audio=False,timeline=timeline,
                change='Opening pause holds welcome frame 0; subsequent pauses hold the preceding action final frame. Original broad-silhouette idle clip removed from review pauses.',
                pause_style='One-second still neutral frames for offline review',
                opening_join_mean_pixel_difference_before=before,
                opening_join_mean_pixel_difference_after=after,
                geometry_measurements=measurements,nod_temporal_edit=True,
                live_switching_verified=False,human_visual_accepted=False,output=str(target))
    write(directory/'report.json',report)
    avatar_path=ROOT/'assets/presenter-v1/avatar.json'
    avatar=read(avatar_path)
    avatar['motion_sequence_preview']='../../outputs/motion-review-v3/motion-sequence.mp4'
    write(avatar_path,avatar)
    summary_path=LIB/'validation-summary.json'
    summary=read(summary_path)
    write(LIB/'validation-summary.before-review-v3.json',summary)
    summary['sequence']=str(target.relative_to(ROOT))
    summary['review_pause_style']=report['pause_style']
    summary['review_geometry_validation']='outputs/motion-review-v3/report.json'
    write(summary_path,summary)
    print(json.dumps(dict(status=report['status'],frames=count,seconds=count/25,
                         opening_join_difference_before=before,
                         opening_join_difference_after=after)))


if __name__=='__main__':
    main()
