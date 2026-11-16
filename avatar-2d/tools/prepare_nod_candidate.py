"""Preserve source 1760 and derive a small nod using early frames and temporal reversal."""
import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from prepare_motion_library import ROOT, LIB, FFBIN, foreground_box, read_image, save, encode


def main():
    source = LIB/'incoming-1760/source.mp4'
    work = LIB/'nod-candidate-1760-v1'
    work.mkdir(exist_ok=False)
    reference = read_image(ROOT/'runtime/avatars/presenter_v1/full_imgs/00000000.png')
    rx, ry, rw, rh = foreground_box(reference)
    capture = cv2.VideoCapture(str(source))
    ok, first = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError('Cannot read nod source')
    sx, sy, sw, sh = foreground_box(first)
    scale = rh/sh
    dx = rx+rw/2-scale*(sx+sw/2)
    dy = ry+rh-scale*(sy+sh)
    matrix = np.array([[scale,0,dx],[0,scale,dy]], np.float64)
    intermediate = work/'normalized-full-intermediate.mp4'
    writer = cv2.VideoWriter(str(intermediate), cv2.VideoWriter_fourcc(*'mp4v'), 25, (720,1280))
    if not writer.isOpened():
        raise RuntimeError('Cannot open normalizer encoder')
    early = []
    count = 0
    with (work/'decode.log').open('wb') as errors:
        process = subprocess.Popen([str(FFBIN/'ffmpeg.exe'),'-hide_banner','-v','error','-nostdin',
                                    '-i',str(source),'-vf','fps=25','-t','5','-an',
                                    '-f','rawvideo','-pix_fmt','bgr24','-'],
                                   stdout=subprocess.PIPE, stderr=errors)
        while True:
            data = process.stdout.read(720*1280*3)
            if not data:
                break
            if len(data) != 720*1280*3:
                raise RuntimeError('Partial decoded frame')
            frame = np.frombuffer(data,np.uint8).reshape(1280,720,3)
            frame = cv2.warpAffine(frame,matrix,(720,1280),flags=cv2.INTER_LANCZOS4,
                                   borderMode=cv2.BORDER_CONSTANT,borderValue=0)
            writer.write(frame)
            if count <= 33:
                early.append(frame)
            count += 1
        process.stdout.close()
        code = process.wait()
    writer.release()
    if code or count != 125 or len(early) != 34:
        raise RuntimeError('Incomplete source normalization')
    full = work/'normalized-full-5s.mp4'
    encode(intermediate,full,source)
    # Select from the beginning of the motion, before the pronounced downward head pose.
    # Cosine sampling slows at the turnaround. Frames are repeated/reversed, not synthesized.
    phase = np.linspace(0,2*np.pi,64)
    moving = np.round(33*(1-np.cos(phase))/2).astype(int).tolist()
    indices = [0]*18+moving+[0]*18
    if len(indices) != 100 or min(indices) != 0 or max(indices) != 33:
        raise RuntimeError('Invalid temporal edit')
    silent = work/'nod-candidate-intermediate.mp4'
    writer = cv2.VideoWriter(str(silent),cv2.VideoWriter_fourcc(*'mp4v'),25,(720,1280))
    if not writer.isOpened():
        raise RuntimeError('Cannot open nod candidate encoder')
    for index in indices:
        writer.write(early[index])
    writer.release()
    target = LIB/'prepared/acknowledge-nod-v1.mp4'
    encode(silent,target,source)
    capture = cv2.VideoCapture(str(target))
    decoded = 0
    while capture.read()[0]:
        decoded += 1
    capture.release()
    if decoded != 100:
        raise RuntimeError('Candidate frame count mismatch')
    tiles = []
    for sample in [0,25,38,50,62,75,99]:
        frame = early[indices[sample]].copy()
        save(work/f'candidate-frame-{sample:04d}.jpg',frame)
        head = frame[30:300,240:460]
        tile = cv2.resize(head,(220,270))
        cv2.putText(tile,f'{sample/25:.2f}s / src {indices[sample]}',(5,20),
                    cv2.FONT_HERSHEY_SIMPLEX,.43,(0,255,255),1)
        tiles.append(tile)
    tiles.append(np.zeros_like(tiles[0]))
    save(work/'candidate-face-contact-sheet.jpg',np.vstack([np.hstack(tiles[:4]),np.hstack(tiles[4:])]))
    report = dict(id='acknowledge-nod',label='轻点头（前段往返剪辑候选）',source_id='1760',
                  source=str(source.relative_to(ROOT)),video=str(target.relative_to(ROOT)),
                  normalized_full_source=str(full.relative_to(ROOT)),frames=100,seconds=4,fps=25,
                  width=720,height=1280,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  prepared_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                  constant_transform=matrix.tolist(),source_foreground_box=[sx,sy,sw,sh],
                  reference_foreground_box=[rx,ry,rw,rh],
                  temporal_edit='Cosine-indexed forward/reverse early-motion excerpt with neutral holds; frames repeated, no synthesized in-between frames',
                  source_normalized_frame_indices=indices,source_range_seconds=[0,1.32],
                  strict_decode_passed=True,loop=False,speech_candidate=True,lipsync_tested=False,
                  live_registered=False,human_visual_accepted=False,
                  note='Full source still bows noticeably. Candidate deliberately excludes the deep dip and requires playback review.')
    (work/'edit-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    inspection_path = LIB/'incoming-1760/inspection.json'
    inspection = json.loads(inspection_path.read_text(encoding='utf-8'))
    inspection.update(action='deep-head-dip-source',
                      visual_review='Source still looks downward around 2-3 seconds; early shallow movement used for a separate temporal-edit nod candidate',
                      candidate_manifest=str((work/'edit-manifest.json').relative_to(ROOT)))
    inspection_path.write_text(json.dumps(inspection,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_normalized_frame_indices'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
