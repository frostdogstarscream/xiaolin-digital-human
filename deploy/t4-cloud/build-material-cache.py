"""Precompute graded frames, transition frames, and matching face crops."""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path[:0] = ['/formal', '/eval/avatar-2d/tools']
from grade_presenter_v2 import grade
import cv2
import numpy as np

cv2.setNumThreads(4)
SOURCE = Path('/eval/avatar-2d/runtime/presenter-50fps')
OUTPUT = Path('/formal/material-cache')
OUTPUT.mkdir(exist_ok=True)
config = json.loads(Path('/formal/material-input.json').read_text())
idle_plan = json.loads((SOURCE / 'idle-plan.json').read_text())
shutil.copy2(SOURCE / 'idle-plan.json', OUTPUT / 'idle-plan.json')
if not (OUTPUT / 'idle').exists():
    (OUTPUT / 'idle').symlink_to(SOURCE / 'idle', target_is_directory=True)
arrays = {'idle': np.load(SOURCE / 'idle/frames.npy', mmap_mode='r')}
coords = {'idle': json.loads((SOURCE / 'idle/coords.json').read_text())}
for item in config['clips']:
    name = item['id']
    destination = OUTPUT / name
    destination.mkdir(exist_ok=True)
    original = np.load(SOURCE / name / 'frames.npy', mmap_mode='r')
    coords[name] = json.loads((SOURCE / name / 'coords.json').read_text())
    if not (destination / 'complete.json').exists():
        target = np.lib.format.open_memmap(destination / 'frames.npy', mode='w+', dtype=np.uint8, shape=original.shape)
        faces = np.lib.format.open_memmap(destination / 'faces.npy', mode='w+', dtype=np.uint8, shape=(len(original), 256, 256, 3))
        for index, frame in enumerate(original):
            corrected = grade(frame, np.array(item['correction_Lab'], dtype=np.float32))
            target[index] = corrected
            y1, y2, x1, x2 = coords[name][index]
            faces[index] = cv2.resize(corrected[y1:y2, x1:x2], (256, 256))
            if index % 100 == 0:
                print(json.dumps(dict(stage='grade', action=name, frame=index, total=len(original))), flush=True)
        target.flush()
        faces.flush()
        (destination / 'coords.json').write_text(json.dumps(coords[name]))
        (destination / 'complete.json').write_text(json.dumps(dict(frames=len(original), correction=item['correction_Lab'])))
        del target, faces
    arrays[name] = np.load(destination / 'frames.npy', mmap_mode='r')


def descriptor(frame):
    features = []
    for y1, y2, x1, x2 in [(100, 430, 400, 700), (350, 850, 300, 800), (650, 1150, 250, 850)]:
        gray = cv2.cvtColor(cv2.resize(frame[y1:y2, x1:x2], (40, 40)), cv2.COLOR_BGR2GRAY)
        features.append(np.concatenate([gray.astype(np.float32).ravel(), (cv2.Sobel(gray, cv2.CV_32F, 1, 0) * .15).ravel()]))
    return np.concatenate(features)


def bridge(first, last):
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    small = lambda image: cv2.cvtColor(cv2.resize(image, (540, 960)), cv2.COLOR_BGR2GRAY)
    forward = cv2.resize(flow.calc(small(first), small(last), None), (1080, 1920)) * 2
    backward = cv2.resize(flow.calc(small(last), small(first), None), (1080, 1920)) * 2
    yy, xx = np.mgrid[:1920, :1080].astype(np.float32)
    for index in range(15):
        fraction = (index + 1) / 16
        a = cv2.remap(first, xx - forward[:, :, 0] * fraction, yy - forward[:, :, 1] * fraction,
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        b = cv2.remap(last, xx - backward[:, :, 0] * (1 - fraction), yy - backward[:, :, 1] * (1 - fraction),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        yield fraction, cv2.addWeighted(a, 1 - fraction, b, fraction, 0)


anchors = sorted(set(range(0, 1500, 25)) | {segment['end'] - 1 for segment in idle_plan['segments']} | {329, 803, 1299})
jobs = []
plan = dict(version='graded-transitions-v1', fps=50, bridge_frames=15, entries={}, returns={}, idle_joins={})
for item in config['clips']:
    name = item['id']
    start = descriptor(arrays[name][0])
    velocity = descriptor(arrays[name][4]) - start
    plan['entries'][name] = []
    for anchor in anchors:
        current = descriptor(arrays['idle'][anchor])
        before = descriptor(arrays['idle'][max(0, anchor - 4)])
        cost = float(np.mean(np.abs(current - start)) + .5 * np.mean(np.abs(current - before - velocity)))
        entry = dict(idle_index=anchor, cost=cost)
        plan['entries'][name].append(entry)
        jobs.append((('idle', anchor), (name, 0), entry))
    target = int(round(config['returns'][name] * 50))
    record = dict(idle_index=target)
    plan['returns'][name] = record
    jobs.append(((name, len(arrays[name]) - 1), ('idle', target), record))
for source in idle_plan['segments']:
    for target in idle_plan['segments']:
        if source['start'] != target['start']:
            key = str(source['end'] - 1) + ':' + str(target['start'])
            record = dict(idle_index=target['start'])
            plan['idle_joins'][key] = record
            jobs.append((('idle', source['end'] - 1), ('idle', target['start']), record))
directory = OUTPUT / 'transitions'
directory.mkdir(exist_ok=True)
count = len(jobs) * 15
full = np.lib.format.open_memmap(directory / 'frames.npy', mode='w+', dtype=np.uint8, shape=(count, 1920, 1080, 3))
faces = np.lib.format.open_memmap(directory / 'faces.npy', mode='w+', dtype=np.uint8, shape=(count, 256, 256, 3))
boxes = []
for number, (source, target, record) in enumerate(jobs):
    record['start'] = number * 15
    record['end'] = (number + 1) * 15
    first = arrays[source[0]][source[1]]
    last = arrays[target[0]][target[1]]
    first_box = np.array(coords[source[0]][source[1]], dtype=np.float32)
    last_box = np.array(coords[target[0]][target[1]], dtype=np.float32)
    for offset, (fraction, frame) in enumerate(bridge(first, last)):
        box = np.rint(first_box * (1 - fraction) + last_box * fraction).astype(int)
        y1, y2, x1, x2 = box
        index = number * 15 + offset
        full[index] = frame
        faces[index] = cv2.resize(frame[y1:y2, x1:x2], (256, 256))
        boxes.append(box.tolist())
    if number % 10 == 0:
        print(json.dumps(dict(stage='bridges', completed=number + 1, total=len(jobs))), flush=True)
full.flush()
faces.flush()
(directory / 'coords.json').write_text(json.dumps(boxes))
(OUTPUT / 'transition-plan.json').write_text(json.dumps(plan, indent=2))
(OUTPUT / 'complete.json').write_text(json.dumps(dict(version=plan['version'], transition_frames=count,
                                                      bridge_count=len(jobs), actions=[item['id'] for item in config['clips']])))
print('MATERIAL_CACHE_COMPLETE', flush=True)
