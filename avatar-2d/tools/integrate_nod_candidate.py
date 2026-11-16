"""Register a clearly labelled temporal-edit candidate, then publish matching inference results."""
import argparse
import json
import shutil
from pathlib import Path

import cv2

from prepare_motion_library import ROOT, LIB, encode


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['register','finalize'])
    parser.add_argument('--output')
    args=parser.parse_args()
    path=LIB/'action-library.json'
    library=read(path)
    if args.operation=='register':
        if any(a['id']=='acknowledge-nod' for a in library['actions']):
            raise RuntimeError('Nod candidate is already registered')
        backup=LIB/'action-library.before-nod-1760.json'
        if backup.exists():
            raise RuntimeError('Registration backup already exists')
        shutil.copy2(path,backup)
        candidate=read(LIB/'nod-candidate-1760-v1/edit-manifest.json')
        candidate['candidate_only']=True
        candidate['visual_review']='Early-frame temporal edit inspected in a sampled sheet; playback acceptance pending'
        library['actions'].append(candidate)
        library['status']='THREE_MOTIONS_TESTED_NOD_TEMPORAL_EDIT_CANDIDATE_PENDING'
        library['pending_visual_actions']=['acknowledge-nod']
        write(path,library)
        print('Registered temporal-edit nod candidate; original source and previous library retained.')
        return
    if not args.output:
        raise ValueError('--output is required for finalization')
    action=next(a for a in library['actions'] if a['id']=='acknowledge-nod')
    output=(ROOT/'outputs'/args.output).resolve()
    if not output.is_relative_to((ROOT/'outputs').resolve()):
        raise ValueError('Output must be inside outputs')
    report=read(output/'report.json')
    validation=read(output/'validation.json')
    if (report['motion']!='acknowledge-nod' or report['frames']!=100 or
            report['avatar']['source_sha256']!=action['prepared_sha256'] or
            validation['status']!='TECHNICAL_MEDIA_CHECK_PASSED' or
            validation['decoded_frames']!=100):
        raise RuntimeError('Candidate inference validation mismatch')
    action.update(lipsync_tested=True,lipsync_output=str(Path(report['output']).relative_to(ROOT)),
                  lipsync_report=str((output/'report.json').relative_to(ROOT)),
                  technical_validation=str((output/'validation.json').relative_to(ROOT)),
                  human_phoneme_sync_accepted=False)
    write(LIB/'prepared/acknowledge-nod-v1.json',action)
    library['status']='FOUR_MOTION_INFERENCE_TESTS_PASSED_NOD_EDIT_VISUAL_REVIEW_REQUIRED'
    library['missing_requested_actions']=[]
    library['missing_reason']=''
    library['nod_source_caveat']='Full source 1760 still bows; only the separate early-motion temporal edit is a nod candidate. Human acceptance remains pending.'
    write(path,library)
    # Keep v1 (with the deep bow) intact, and build the requested four-action review separately.
    demo=ROOT/'outputs/motion-review-v2'
    demo.mkdir(exist_ok=False)
    silent=demo/'sequence-intermediate.mp4'
    writer=cv2.VideoWriter(str(silent),cv2.VideoWriter_fourcc(*'mp4v'),25,(720,1280))
    if not writer.isOpened():
        raise RuntimeError('Cannot open sequence writer')
    timeline=[]
    cursor=0
    def append(video, name, limit=None):
        nonlocal cursor
        cap=cv2.VideoCapture(str(video))
        start=cursor
        while limit is None or cursor-start<limit:
            ok,frame=cap.read()
            if not ok:
                break
            writer.write(frame)
            cursor+=1
        cap.release()
        if cursor==start:
            raise RuntimeError('Empty review segment')
        timeline.append(dict(action=name,start_frame=start,end_frame_exclusive=cursor,
                             start_seconds=start/25,end_seconds=cursor/25))
    idle=ROOT/library['idle']
    append(idle,'idle',25)
    for key in ['welcome-wave','explain-open-palms','acknowledge-nod','goodbye-wave']:
        selected=next(a for a in library['actions'] if a['id']==key)
        append(ROOT/selected['video'],key)
        append(idle,'idle',25)
    writer.release()
    target=demo/'motion-sequence.mp4'
    encode(silent,target)
    cap=cv2.VideoCapture(str(target))
    count=0
    while cap.read()[0]:
        count+=1
    cap.release()
    if count!=cursor or cursor!=800:
        raise RuntimeError('Complete sequence frame mismatch')
    write(demo/'report.json',dict(status='OFFLINE_MOTION_SEQUENCE_DECODE_PASSED',frames=count,
                                 fps=25,seconds=count/25,audio=False,timeline=timeline,
                                 nod_temporal_edit=True,nod_human_accepted=False,
                                 live_switching_verified=False,output=str(target)))
    summary=read(LIB/'validation-summary.json')
    write(LIB/'validation-summary.before-nod-1760.json',summary)
    summary.update(status=library['status'],imported_files=5,source_frames=845,
                   normalized_motion_frames=sum(a['frames'] for a in library['actions']),
                   subtle_nod_available='temporal-edit candidate only',nod_human_accepted=False,
                   sequence=str(target.relative_to(ROOT)))
    summary['speaking_motion_tests'].append(dict(id='acknowledge-nod',frames=100,seconds=4,
                                                output=action['lipsync_output'],
                                                peak_allocated_gpu_mb=report['peak_allocated_gpu_mb'],
                                                pipeline_fps=report['pipeline_fps'],
                                                validation=validation['status']))
    write(LIB/'validation-summary.json',summary)
    avatar_path=ROOT/'assets/presenter-v1/avatar.json'
    avatar=read(avatar_path)
    avatar.update(stage='four_local_motion_tests_available_nod_edit_visual_review_pending',
                  motion_sequence_preview='../../outputs/motion-review-v2/motion-sequence.mp4',
                  nod_human_accepted=False)
    write(avatar_path,avatar)
    print(json.dumps(dict(status=library['status'],nod_frames=100,sequence_frames=count,
                         sequence_seconds=count/25),ensure_ascii=False))


if __name__=='__main__':
    main()
