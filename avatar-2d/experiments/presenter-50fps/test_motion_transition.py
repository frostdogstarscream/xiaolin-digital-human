"""Offline comparison of idle/action cuts and optical-flow transitions."""
import argparse
import functools
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from grade_presenter_v2 import grade
import cv2
import numpy as np

cv2.setNumThreads(4)
OUTPUT = ROOT / 'outputs/welcome-transition-20261111'
FFMPEG = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
FPS = 50
BRIDGE_FRAMES = 15
REGIONS = [(100, 430, 400, 700), (350, 850, 300, 800), (650, 1150, 250, 850)]


class Frames:
    def __init__(self, action='welcome-wave'):
        cache = ROOT / 'runtime/presenter-v2-1080/avatars'
        self.arrays = {name: np.load(cache / name / 'frames.npy', mmap_mode='r')
                       for name in ['idle', action]}
        manifest = json.loads((ROOT / 'assets/presenter-v2-1080/color-matched-20261111/manifest.json').read_text(encoding='utf-8'))
        corrections = {item['id']: item['correction_Lab'] for item in manifest['clips']}
        self.correction = np.array(corrections[action], dtype=np.float32)

    @functools.lru_cache(maxsize=32)
    def native(self, name, index):
        frame = self.arrays[name][index]
        return frame if name == 'idle' else grade(frame, self.correction)

    @functools.lru_cache(maxsize=32)
    def at50(self, name, index):
        first = self.native(name, index // 2)
        if index % 2 == 0 or index // 2 + 1 >= len(self.arrays[name]):
            return first
        second = self.native(name, index // 2 + 1)
        return optical_bridge(first, second, [0.5])[0]


def optical_bridge(first, second, fractions):
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    gray = lambda frame: cv2.cvtColor(cv2.resize(frame, (540, 960)), cv2.COLOR_BGR2GRAY)
    forward = flow.calc(gray(first), gray(second), None)
    backward = flow.calc(gray(second), gray(first), None)
    forward = cv2.resize(forward, (1080, 1920)) * 2
    backward = cv2.resize(backward, (1080, 1920)) * 2
    yy, xx = np.mgrid[:1920, :1080].astype(np.float32)
    result = []
    for fraction in fractions:
        a = cv2.remap(first, xx - forward[:, :, 0] * fraction,
                      yy - forward[:, :, 1] * fraction, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE)
        b = cv2.remap(second, xx - backward[:, :, 0] * (1 - fraction),
                      yy - backward[:, :, 1] * (1 - fraction), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE)
        result.append(cv2.addWeighted(a, 1 - fraction, b, fraction, 0))
    return result


def descriptor(frame):
    features = []
    for y1, y2, x1, x2 in REGIONS:
        gray = cv2.cvtColor(cv2.resize(frame[y1:y2, x1:x2], (40, 40)), cv2.COLOR_BGR2GRAY)
        edges = cv2.Sobel(gray, cv2.CV_32F, 1, 0) * .15
        features.append(np.concatenate([gray.astype(np.float32).ravel(), edges.ravel()]))
    return np.concatenate(features)


def writer(path, width, height):
    return subprocess.Popen([
        str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}',
        '-r', str(FPS), '-i', '-', '-an', '-c:v', 'libx264', '-crf', '17',
        '-preset', 'fast', '-threads', '4', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(path),
    ], stdin=subprocess.PIPE)


def finish(process):
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError('Video encoder failed')


def segment(name, start, count, phase):
    return [(name, index, phase) for index in range(start, start + count)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=['welcome-wave', 'goodbye-wave', 'explain-open-palms', 'acknowledge-nod'], default='welcome-wave')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output
    output.mkdir(exist_ok=True, parents=True)
    action_name = args.action
    basename = 'welcome' if action_name == 'welcome-wave' else action_name
    frames = Frames(action_name)
    native_count = len(frames.arrays[action_name])
    action_count = native_count * 2
    idle_desc = np.array([descriptor(frames.native('idle', i)) for i in range(750)])
    start_desc = descriptor(frames.native(action_name, 0))
    start_velocity = descriptor(frames.native(action_name, 2)) - start_desc
    end_desc = descriptor(frames.native(action_name, native_count - 1))
    end_velocity = end_desc - descriptor(frames.native(action_name, native_count - 3))

    def entry_cost(index):
        appearance = np.mean(np.abs(idle_desc[index] - start_desc))
        velocity = np.mean(np.abs(idle_desc[index] - idle_desc[index - 2] - start_velocity))
        return float(appearance + .5 * velocity)

    def return_cost(index):
        appearance = np.mean(np.abs(idle_desc[index] - end_desc))
        velocity = np.mean(np.abs(idle_desc[index + 2] - idle_desc[index] - end_velocity))
        return float(appearance + .5 * velocity)

    entries = []
    for request in [150, 400, 650]:
        chosen = min(range(request, request + 16), key=entry_cost)
        entries.append(dict(request_seconds=request / 25, selected_seconds=chosen / 25,
                            wait_seconds=(chosen - request) / 25,
                            direct_cost=entry_cost(request), selected_cost=entry_cost(chosen)))
    # Keep enough idle frames for the 2 s tail and the shorter comparison's padding.
    return_limit = len(frames.arrays['idle']) - (100 + 2 * BRIDGE_FRAMES) // 2
    returned = min(range(25, return_limit + 1), key=return_cost)
    request = 400
    chosen = round(entries[1]['selected_seconds'] * 25)
    pre = segment('idle', request * 2 - 100, 100, 'idle')
    action = segment(action_name, 0, action_count, action_name)
    waiting = segment('idle', request * 2, (chosen - request) * 2, 'wait for entry')
    direct = pre + action + segment('idle', 0, 100, 'return to idle')
    matched = pre + waiting + action + segment('idle', returned * 2, 100, 'matched idle')
    entry_first = frames.at50('idle', chosen * 2 - 1)
    entry_last = frames.at50(action_name, 0)
    return_first = frames.at50(action_name, action_count - 1)
    return_last = frames.at50('idle', returned * 2)
    fractions = [(i + 1) / (BRIDGE_FRAMES + 1) for i in range(BRIDGE_FRAMES)]
    bridges = {
        'entry': optical_bridge(entry_first, entry_last, fractions),
        'return': optical_bridge(return_first, return_last, fractions),
    }
    entry_tokens = [('entry', i, 'entry transition') for i in range(BRIDGE_FRAMES)]
    return_tokens = [('return', i, 'return transition') for i in range(BRIDGE_FRAMES)]
    transitioned = pre + waiting + entry_tokens + action + return_tokens + segment('idle', returned * 2, 100, 'matched idle')
    sequences = [direct, matched, transitioned]
    names = ['A / direct cut', 'B / image + motion match', 'C / match + flow bridge']
    total = len(transitioned)
    # Keep idle moving when shorter variants finish, instead of holding a still frame.
    for sequence in sequences:
        tail = sequence[-1]
        sequence.extend(segment('idle', tail[1] + 1, total - len(sequence), 'idle'))

    def resolve(token):
        name, index, _ = token
        return bridges[name][index] if name in bridges else frames.at50(name, index)

    seam_rows = []
    for label, first, last, bridge in [
        ('entry', entry_first, entry_last, bridges['entry']),
        ('return', return_first, return_last, bridges['return']),
    ]:
        images = [first, bridge[3], bridge[7], bridge[11], last]
        tiles = []
        for i, image in enumerate(images):
            crop = cv2.resize(image[80:1150, 250:830], (290, 535))
            cv2.putText(crop, f'{label} {i}', (8, 25), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 1)
            tiles.append(crop)
        seam_rows.append(np.hstack(tiles))
    cv2.imencode('.jpg', np.vstack(seam_rows), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(output / 'transition-details.jpg'))

    comparison = writer(output / 'three-way-comparison-50fps.mp4', 1620, 1000)
    candidate_name = basename + '-with-transitions-50fps.mp4'
    candidate = writer(output / candidate_name, 1080, 1920)
    for index in range(total):
        images = [resolve(sequence[index]) for sequence in sequences]
        panels = []
        for title, sequence, image in zip(names, sequences, images):
            panel = cv2.copyMakeBorder(cv2.resize(image, (540, 960)), 40, 0, 0, 0, cv2.BORDER_CONSTANT)
            cv2.putText(panel, title, (9, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, (240, 240, 240), 1)
            cv2.putText(panel, sequence[index][2], (9, 34), cv2.FONT_HERSHEY_SIMPLEX, .42, (100, 220, 200), 1)
            panels.append(panel)
        comparison.stdin.write(np.hstack(panels).tobytes())
        candidate.stdin.write(images[2].tobytes())
        if index % 100 == 0:
            print(json.dumps(dict(action=action_name, frame=index, total=total)), flush=True)
    finish(comparison)
    finish(candidate)
    report = dict(action=action_name, candidate_file=candidate_name,
                  fps=FPS, frames=total, seconds=total / FPS, bridge_frames=BRIDGE_FRAMES,
                  bridge_seconds=BRIDGE_FRAMES / FPS, action_frames=action_count, action_seconds=action_count / FPS,
                  entry_trials=entries, main_trial_request_seconds=16,
                  returned_idle_seconds=returned / 25,
                  baseline_return_cost=return_cost(0), selected_return_cost=return_cost(returned),
                  method='Offline weighted face/torso/hand image and velocity descriptors. Bidirectional DIS bridge. No skeleton keypoint model.',
                  visual_review_required=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
