"""Match action skin tones to the idle reference and export separate video masters."""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from windows_runtime import prepare_runtime

prepare_runtime()
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
OUTPUT = ROOT / 'assets/presenter-v2-1080/color-matched-20261111'
cv2.setNumThreads(4)


def cheek_color(frame, box):
    y1, y2, x1, x2 = box
    face = cv2.resize(frame[y1:y2, x1:x2], (256, 256))
    lab = cv2.cvtColor(face.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    patches = np.concatenate([
        lab[125:155, 35:65].reshape(-1, 3),
        lab[125:155, 191:221].reshape(-1, 3),
    ])
    return np.median(patches, axis=0)


def skin_mask(frame):
    # Soft chroma limits retain gradual skin boundaries and exclude the blue shirt.
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    luminance, cr, cb = cv2.split(ycrcb)
    factors = [
        np.clip((luminance - 30) / 25, 0, 1),
        np.clip((cr - 130) / 10, 0, 1),
        np.clip((180 - cr) / 10, 0, 1),
        np.clip((138 - cb) / 12, 0, 1),
        np.clip((cb - 70) / 12, 0, 1),
        np.clip((hsv[:, :, 1] - 18) / 18, 0, 1),
        np.clip((28 - hsv[:, :, 0]) / 8, 0, 1),
    ]
    mask = np.minimum.reduce(factors)
    return cv2.GaussianBlur(mask, (0, 0), 2.5)


def grade(frame, correction):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
    # OpenCV uint8 Lab stores L* on 0..255 and a*/b* with a 128 offset.
    shift = correction * np.array([2.55, 1, 1], dtype=np.float32)
    corrected = np.clip(lab + shift, 0, 255).astype(np.uint8)
    corrected = cv2.cvtColor(corrected, cv2.COLOR_LAB2BGR)
    mask = skin_mask(frame)[..., None]
    return np.rint(frame * (1 - mask) + corrected * mask).clip(0, 255).astype(np.uint8)


def writer(path, width, height):
    return subprocess.Popen([
        str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}',
        '-r', '25', '-i', '-', '-an', '-c:v', 'libx264', '-crf', '15',
        '-preset', 'fast', '-threads', '4', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(path),
    ], stdin=subprocess.PIPE)


def finish(process):
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError('Video encoding failed')


def face_tile(frame, box, label):
    y1, y2, x1, x2 = box
    face = cv2.resize(frame[y1:y2, x1:x2], (256, 320))
    tile = cv2.copyMakeBorder(face, 30, 0, 0, 0, cv2.BORDER_CONSTANT)
    cv2.putText(tile, label, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, .5, (240, 240, 240), 1)
    return tile


def comparison_frame(original, corrected, label):
    pair = np.hstack([cv2.resize(original, (540, 960)), cv2.resize(corrected, (540, 960))])
    pair = cv2.copyMakeBorder(pair, 40, 0, 0, 0, cv2.BORDER_CONSTANT)
    for text, x in [(label + ' / original', 12), ('color matched', 552)]:
        cv2.putText(pair, text, (x, 27), cv2.FONT_HERSHEY_SIMPLEX, .65, (240, 240, 240), 1)
    return pair


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview-only', action='store_true')
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    profile = json.loads((ROOT / 'assets/presenter-v2-1080/profile.json').read_text(encoding='utf-8'))
    idle_dir = ROOT / profile['idle']['avatar_dir']
    idle = np.load(idle_dir / 'frames.npy', mmap_mode='r')
    idle_boxes = json.loads((idle_dir / 'coords.json').read_text(encoding='utf-8'))
    idle_indices = np.linspace(0, len(idle) - 1, 11).astype(int)
    reference = np.median([cheek_color(idle[i], idle_boxes[i]) for i in idle_indices], axis=0)
    rows = [np.hstack([
        face_tile(idle[0], idle_boxes[0], 'idle reference'),
        face_tile(idle[len(idle) // 2], idle_boxes[len(idle) // 2], 'idle middle'),
        face_tile(idle[-1], idle_boxes[-1], 'idle end'),
    ])]
    records = []
    comparison = None
    if not args.preview_only:
        comparison = writer(OUTPUT / 'before-after.mp4', 1080, 1000)
        for i in range(50):
            comparison.stdin.write(comparison_frame(idle[i], idle[i], 'idle reference').tobytes())
    for item in profile['actions']:
        started = time.monotonic()
        name = item['id']
        directory = ROOT / item['avatar_dir']
        frames = np.load(directory / 'frames.npy', mmap_mode='r')
        boxes = json.loads((directory / 'coords.json').read_text(encoding='utf-8'))
        indices = np.linspace(0, len(frames) - 1, 11).astype(int)
        before = np.median([cheek_color(frames[i], boxes[i]) for i in indices], axis=0)
        correction = reference - before
        after = np.median([cheek_color(grade(frames[i], correction), boxes[i]) for i in indices], axis=0)
        rows.append(np.hstack([
            face_tile(frames[0], boxes[0], name + ' original'),
            face_tile(grade(frames[0], correction), boxes[0], 'matched start'),
            face_tile(grade(frames[len(frames) // 2], correction), boxes[len(frames) // 2], 'matched middle'),
        ]))
        record = dict(id=name, frames=len(frames), fps=25, seconds=len(frames) / 25,
                      source=str(directory / 'frames.npy'), reference_Lab=reference.tolist(),
                      correction_Lab=correction.tolist(), before_Lab=before.tolist(), after_Lab=after.tolist(),
                      before_delta_E76=float(np.linalg.norm(before - reference)),
                      after_delta_E76=float(np.linalg.norm(after - reference)))
        if not args.preview_only:
            target = OUTPUT / (name + '.mp4')
            temporary = OUTPUT / (name + '.partial.mp4')
            process = writer(temporary, 1080, 1920)
            for index, frame in enumerate(frames):
                corrected = grade(frame, correction)
                process.stdin.write(corrected.tobytes())
                comparison.stdin.write(comparison_frame(frame, corrected, name).tobytes())
            finish(process)
            temporary.replace(target)
            record['output'] = str(target)
            record['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        record['elapsed_seconds'] = time.monotonic() - started
        records.append(record)
        print(json.dumps(record), flush=True)
    if comparison:
        finish(comparison)
    cv2.imencode('.jpg', np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(OUTPUT / 'before-after-faces.jpg'))
    report = dict(reference='idle, 11 sampled frames, median normalized cheek Lab',
                  method='One fixed Lab offset per clip, soft skin chroma mask, spatial feathering. Same correction across all frames.',
                  native_fps=25, native_resolution=[1080, 1920], preview_only=args.preview_only, clips=records)
    name = 'preview-measurements.json' if args.preview_only else 'manifest.json'
    (OUTPUT / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
