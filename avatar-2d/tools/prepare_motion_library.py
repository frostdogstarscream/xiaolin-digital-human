"""Normalize supplied gestures with one fixed transform per clip and retain provenance."""
import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'assets/presenter-v1/motions-v1'
FFBIN = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin'
SPECS = [
    ('welcome-wave', '迎宾挥手', '8580', 7, True),
    ('goodbye-wave', '告别挥手', '6386', 7, True),
    ('explain-open-palms', '摊手讲解', '8687', 9, True),
    ('bow-greeting', '低头致意（非轻点头）', '8571', 7, False),
]


def read_image(path):
    return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)


def save(path, image):
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError('Image encoding failed')
    path.write_bytes(data.tobytes())


def foreground_box(frame):
    # Black-background geometry heuristic only; not an identity or quality acceptance metric.
    mask = (frame.max(axis=2) > 18).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    accepted = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 500]
    filtered = np.isin(labels, accepted).astype(np.uint8)
    if not accepted:
        raise RuntimeError('Could not locate presenter against black background')
    return cv2.boundingRect(filtered)


def encode(silent, target, metadata_source=None):
    command = [str(FFBIN/'ffmpeg.exe'), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-i', str(silent)]
    if metadata_source:
        command += ['-i', str(metadata_source), '-map_metadata', '1']
    command += ['-map', '0:v:0', '-an', '-c:v', 'libx264', '-crf', '18', '-preset', 'medium',
                '-movflags', '+faststart+use_metadata_tags', '-metadata',
                'comment=AI-generated presenter; local motion preparation', str(target)]
    subprocess.run(command, check=True)
    subprocess.run([str(FFBIN/'ffmpeg.exe'), '-hide_banner', '-v', 'error', '-xerror',
                    '-i', str(target), '-map', '0:v:0', '-f', 'null', '-'], check=True)


def main():
    reference = read_image(ROOT/'runtime/avatars/presenter_v1/full_imgs/00000000.png')
    rx, ry, rw, rh = foreground_box(reference)
    prepared = LIB/'prepared'
    prepared.mkdir(exist_ok=False)
    actions = []
    comparison = []
    for action_id, label, key, seconds, speech in SPECS:
        incoming = LIB / ('incoming-' + key)
        source = incoming/'source.mp4'
        cap = cv2.VideoCapture(str(source))
        ok, first = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError('Could not decode supplied motion')
        sx, sy, sw, sh = foreground_box(first)
        scale = rh/sh
        dx = rx+rw/2-scale*(sx+sw/2)
        dy = ry+rh-scale*(sy+sh)
        matrix = np.array([[scale, 0, dx], [0, scale, dy]], dtype=np.float64)
        silent = prepared/(action_id+'-intermediate.mp4')
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*'mp4v'), 25, (720, 1280))
        if not writer.isOpened():
            raise RuntimeError('Cannot open intermediate encoder')
        expected = seconds*25
        samples = []
        with (prepared/(action_id+'-decode.log')).open('wb') as errors:
            process = subprocess.Popen([str(FFBIN/'ffmpeg.exe'), '-hide_banner', '-v', 'error',
                                        '-nostdin', '-i', str(source), '-vf', 'fps=25', '-t', str(seconds),
                                        '-an', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                                       stdout=subprocess.PIPE, stderr=errors)
            count = 0
            while True:
                data = process.stdout.read(720*1280*3)
                if not data:
                    break
                if len(data) != 720*1280*3:
                    raise RuntimeError('Truncated raw frame')
                frame = np.frombuffer(data, np.uint8).reshape(1280, 720, 3)
                aligned = cv2.warpAffine(frame, matrix, (720, 1280), flags=cv2.INTER_LANCZOS4,
                                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                writer.write(aligned)
                if count in [0, expected//2, expected-1]:
                    save(prepared/f'{action_id}-frame-{count:04d}.jpg', aligned)
                    tile = cv2.resize(aligned, (200, 356))
                    cv2.putText(tile, f'{action_id} / {count/25:.2f}s', (5, 20),
                                cv2.FONT_HERSHEY_SIMPLEX, .36, (0, 255, 255), 1)
                    samples.append(tile)
                count += 1
            process.stdout.close()
            code = process.wait()
        writer.release()
        if code or count != expected:
            raise RuntimeError(f'Normalization failed: {action_id}, {code}, {count}/{expected}')
        target = prepared/(action_id+'.mp4')
        encode(silent, target, source)
        # Confirm the final delivery, not only its intermediate.
        capture = cv2.VideoCapture(str(target))
        decoded = 0
        while capture.read()[0]:
            decoded += 1
        capture.release()
        if decoded != expected:
            raise RuntimeError('Final encoded motion frame count mismatch')
        report = dict(id=action_id, label=label, source_id=key,
                      source=str(source.relative_to(ROOT)), video=str(target.relative_to(ROOT)),
                      frames=count, seconds=seconds, fps=25, width=720, height=1280,
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      prepared_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                      constant_transform=matrix.tolist(), source_foreground_box=[sx,sy,sw,sh],
                      reference_foreground_box=[rx,ry,rw,rh],
                      alignment_method='Constant uniform scale and translation using first-frame black-background extent; no per-frame stabilization or face warping',
                      strict_decode_passed=True, loop=False, speech_candidate=speech,
                      lipsync_tested=False, live_registered=False,
                      visual_review='Sampled full-body and face inspection; not exhaustive hand/identity acceptance',
                      note='Head dips substantially; keep as silent bow, not subtle nod' if not speech else '')
        (prepared/(action_id+'.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        actions.append(report)
        comparison.append(np.hstack(samples))
        print(json.dumps(dict(id=action_id, frames=count, scale=scale, translation=[dx,dy])), flush=True)
    save(prepared/'alignment-contact-sheet.jpg', np.vstack(comparison))
    library = dict(schema_version=1, status='PREPARED_OFFLINE_MOTION_ASSETS', fps=25,
                   idle='assets/presenter-v1/idle-fullbody-20s-25fps-v1.mp4', actions=actions,
                   missing_requested_actions=['subtle-acknowledgement-nod'],
                   missing_reason='Supplied 8571 performs a pronounced head dip/bow, not a subtle nod',
                   source_mapping='Two wave clips assigned by observed timing: earlier wave 8580 welcomes; slower wave 6386 says goodbye',
                   live_switching_verified=False, realtime_streaming_verified=False)
    (LIB/'action-library.json').write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding='utf-8')
    # Actual decoded concatenation, preserving complete motions without crossfade ghosting.
    demo = ROOT/'outputs/motion-review-v1'
    demo.mkdir(exist_ok=False)
    intermediate = demo/'sequence-intermediate.mp4'
    writer = cv2.VideoWriter(str(intermediate), cv2.VideoWriter_fourcc(*'mp4v'), 25, (720,1280))
    if not writer.isOpened():
        raise RuntimeError('Cannot open sequence encoder')
    timeline, cursor = [], 0
    def append_clip(path, name, limit=None):
        nonlocal cursor
        start = cursor
        capture = cv2.VideoCapture(str(path))
        frames = 0
        while limit is None or frames < limit:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            frames += 1
        capture.release()
        if frames == 0:
            raise RuntimeError('Empty sequence segment')
        cursor += frames
        timeline.append(dict(action=name, start_frame=start, end_frame_exclusive=cursor,
                             start_seconds=start/25, end_seconds=cursor/25))
    idle = ROOT/library['idle']
    append_clip(idle, 'idle', 25)
    for action_id in ['welcome-wave', 'explain-open-palms', 'bow-greeting', 'goodbye-wave']:
        append_clip(prepared/(action_id+'.mp4'), action_id)
        append_clip(idle, 'idle', 25)
    writer.release()
    final = demo/'motion-sequence.mp4'
    encode(intermediate, final)
    capture = cv2.VideoCapture(str(final))
    decoded = 0
    while capture.read()[0]:
        decoded += 1
    capture.release()
    if decoded != cursor:
        raise RuntimeError('Sequence frame count mismatch')
    report = dict(status='OFFLINE_MOTION_SEQUENCE_DECODE_PASSED', frames=cursor, fps=25,
                  seconds=cursor/25, audio=False, timeline=timeline,
                  transition='Direct cuts at matched neutral poses; residual pose and appearance differences require playback review',
                  live_switching_verified=False, output=str(final))
    (demo/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
