"""Render three audio-identical variants using the deployed material and model caches."""
import argparse
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

BASE = Path('/formal/smile-review-20261111')
OUTPUT = BASE
sys.path[:0] = [str(BASE / 'libs'), '/formal/avatar-2d/experiments/presenter-50fps']
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision
import engine50 as engine
from avatars.wav2lip import audio

cv2.setNumThreads(2)
SPEECH_START = 120
LEAD_FRAMES = 10
HOLD_FRAMES = 6
FADE_FRAMES = 12


def writer(path, width, height):
    return subprocess.Popen([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', '50', '-i', '-',
        '-i', str(OUTPUT / 'timeline.wav'), '-c:v', 'libx264', '-preset', 'fast', '-threads', '2',
        '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest',
        '-movflags', '+faststart', str(path),
    ], stdin=subprocess.PIPE)


def finish(process):
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError('Video encoding failed')


def face_preview(frame, box, size=(384, 480)):
    y1, y2, x1, x2 = box
    height = (y2 - y1) * 1.35
    width = height * .8
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    top = max(0, round(center_y - height / 2))
    left = max(0, round(center_x - width / 2))
    crop = frame[top:top + round(height), left:left + round(width)]
    return cv2.resize(crop, size)


class LipMask:
    def __init__(self):
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(BASE / 'face_landmarker.task'),
                                     delegate=BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE, num_faces=1,
            min_face_detection_confidence=.4, min_face_presence_confidence=.4)
        self.detector = vision.FaceLandmarker.create_from_options(options)
        self.ids = sorted({point for connection in vision.FaceLandmarksConnections.FACE_LANDMARKS_LIPS
                           for point in [connection.start, connection.end]})
        self.smoothed = {}
        self.failures = 0
        self.total = 0

    def points(self, image, name):
        rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        result = self.detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        self.total += 1
        if not result.face_landmarks:
            self.failures += 1
            return None
        landmarks = result.face_landmarks[0]
        raw = np.array([[landmarks[index].x * 256, landmarks[index].y * 256] for index in self.ids], np.float32)
        previous = self.smoothed.get(name, raw)
        smoothed = .55 * raw + .45 * previous
        self.smoothed[name] = smoothed
        # Include current points so smoothing cannot expose a moving mouth edge.
        return np.vstack([raw, smoothed])

    def mask(self, source, prediction):
        reference = self.points(source, 'source')
        generated = self.points(prediction, 'prediction')
        if reference is None or generated is None:
            return None
        points = np.rint(np.vstack([reference, generated])).clip(0, 255).astype(np.int32)
        hull = cv2.convexHull(points)
        mask = np.zeros((256, 256), np.uint8)
        cv2.fillConvexPoly(mask, hull, 255)
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
        soft = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 4)
        return np.clip(soft * 1.15, 0, 1)


def main():
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=['welcome-wave', 'goodbye-wave', 'explain-open-palms', 'acknowledge-nod'], default='welcome-wave')
    parser.add_argument('--output', type=Path, default=BASE)
    parser.add_argument('--two-way', action='store_true')
    args = parser.parse_args()
    OUTPUT = args.output
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assets = engine.Assets()
    presenter = engine.Presenter(engine.options('smile-review-offline'), assets, lambda event: None)
    presenter.idle_scheduler.seek(700)
    presenter.pose = ('idle', 699)
    tokens = []
    tail = None
    for index in range(800):
        if index == 100:
            presenter.request_motion(args.action)
        tokens.append(presenter._advance([]))
        if presenter.transitions.completed[args.action]:
            if tail is None:
                tail = 100
            else:
                tail -= 1
                if tail == 0:
                    break
    assert presenter.transitions.completed[args.action] == 1
    count = len(tokens)
    with wave.open(str(BASE / 'welcome-16k.wav'), 'rb') as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (16000, 1, 2)
        greeting = np.frombuffer(reader.readframes(reader.getnframes()), np.int16).astype(np.float32) / 32768
    driving = np.zeros(count * 320, np.float32)
    start_sample = SPEECH_START * 320
    assert start_sample + len(greeting) < len(driving)
    driving[start_sample:start_sample + len(greeting)] = greeting
    with wave.open(str(OUTPUT / 'timeline.wav'), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(np.rint(driving * 32768).clip(-32768, 32767).astype(np.int16).tobytes())
    speech_end = SPEECH_START + int(np.ceil(len(greeting) / 320))
    fade_start = speech_end + HOLD_FRAMES
    fade_end = fade_start + FADE_FRAMES
    mel = audio.melspectrogram(driving)
    mask_builder = LipMask()
    selected = [0, 2] if args.two_way else [0, 1, 2]
    all_files = ['A-current-50fps.mp4', 'B-sentence-fade-50fps.mp4', 'C-lip-landmarks-50fps.mp4']
    all_labels = ['A / current', 'B / sentence + fade', 'C / B + lip landmarks']
    output_files = [all_files[index] for index in selected]
    labels = [all_labels[index] for index in selected]
    processes = [writer(OUTPUT / name, 1080, 1920) for name in output_files]
    comparison_name = 'AC-audible-comparison-50fps.mp4' if args.two_way else 'ABC-audible-comparison-50fps.mp4'
    comparison_width = len(selected) * 384
    comparison = writer(OUTPUT / comparison_name, comparison_width, 1202)
    rows = []
    samples = {SPEECH_START, SPEECH_START + 70, speech_end - 1, speech_end, fade_start + 6, fade_end}
    fallback_frames = []
    landmark_frames = 0
    for begin in range(0, count, 4):
        indices = list(range(begin, min(count, begin + 4)))
        features = [mel[:, min(int(index * 80 / 50), mel.shape[1] - 16):min(int(index * 80 / 50), mel.shape[1] - 16) + 16]
                    for index in indices]
        predictions = presenter._infer([tokens[index] for index in indices], features)
        for index, prediction in zip(indices, predictions):
            token = tokens[index]
            source = assets.frame(*token).copy()
            box = assets.clips[token[0]][1][token[1]]
            current = presenter._compose(token, prediction) if SPEECH_START <= index < speech_end else source.copy()
            if index < SPEECH_START - LEAD_FRAMES or index >= fade_end:
                envelope = 0.
            elif index < SPEECH_START:
                envelope = (index - (SPEECH_START - LEAD_FRAMES) + 1) / LEAD_FRAMES
            elif index < fade_start:
                envelope = 1.
            else:
                fraction = (index - fade_start + 1) / FADE_FRAMES
                envelope = 1 - fraction * fraction * (3 - 2 * fraction)
            broad = presenter._compose(token, prediction)
            sentence = np.rint(source * (1 - envelope) + broad * envelope).clip(0, 255).astype(np.uint8)
            lips = source.copy()
            if envelope > 0:
                y1, y2, x1, x2 = box
                reference = cv2.resize(source[y1:y2, x1:x2], (256, 256))
                mask = mask_builder.mask(reference, prediction)
                if mask is None:
                    lips = sentence.copy()
                    fallback_frames.append(index)
                else:
                    landmark_frames += 1
                    height, width = y2 - y1, x2 - x1
                    alpha = cv2.resize(mask, (width, height))[..., None] * envelope
                    patch = cv2.resize(prediction, (width, height))
                    lips[y1:y2, x1:x2] = np.rint(patch * alpha + source[y1:y2, x1:x2] * (1 - alpha)).clip(0, 255).astype(np.uint8)
                    if index == SPEECH_START + 70:
                        debug = reference.copy()
                        tint = np.zeros_like(debug)
                        tint[:, :, 1] = 255
                        debug = np.rint(debug * (1 - mask[..., None] * .35) + tint * mask[..., None] * .35).astype(np.uint8)
                        cv2.imencode('.jpg', np.hstack([reference, prediction, debug]), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(OUTPUT / 'lip-mask-debug.jpg'))
            all_variants = [current, sentence, lips]
            variants = [all_variants[index] for index in selected]
            panels = []
            for process, label, frame in zip(processes, labels, variants):
                process.stdin.write(frame.tobytes())
                face = face_preview(frame, box)
                body = cv2.resize(frame, (384, 682))
                panel = cv2.copyMakeBorder(np.vstack([face, body]), 40, 0, 0, 0, cv2.BORDER_CONSTANT)
                cv2.putText(panel, label, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, (240, 240, 240), 1)
                cv2.putText(panel, f'{index / 50:.2f}s', (8, 34), cv2.FONT_HERSHEY_SIMPLEX, .45, (120, 220, 200), 1)
                panels.append(panel)
            comparison.stdin.write(np.hstack(panels).tobytes())
            if index in samples:
                row = []
                for label, frame in zip(labels, variants):
                    tile = face_preview(frame, box, (288, 360))
                    cv2.putText(tile, f'{label} {index / 50:.2f}s', (5, 350), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 255, 255), 1)
                    row.append(tile)
                rows.append(np.hstack(row))
        if begin % 40 == 0:
            print(json.dumps(dict(frame=begin, total=count, landmark_fallbacks=len(fallback_frames))), flush=True)
    for process in [*processes, comparison]:
        finish(process)
    mask_builder.detector.close()
    cv2.imencode('.jpg', np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(OUTPUT / 'face-comparison.jpg'))
    record = dict(action=args.action, fps=50, frames=count, seconds=count / 50, precision=str(assets.dtype),
                  material_version=assets.transition_plan['version'], speech_start_seconds=SPEECH_START / 50,
                  speech_end_seconds=speech_end / 50, hold_seconds=HOLD_FRAMES / 50,
                  fade_seconds=FADE_FRAMES / 50, landmark_frames=landmark_frames,
                  landmark_detection_failures=mask_builder.failures, fallback_frames=fallback_frames,
                  audio_sha256=hashlib.sha256((OUTPUT / 'timeline.wav').read_bytes()).hexdigest(),
                  landmark_model_sha256=hashlib.sha256((BASE / 'face_landmarker.task').read_bytes()).hexdigest(),
                  output_files=[*output_files, comparison_name], comparison_file=comparison_name,
                  comparison_width=comparison_width,
                  variants=labels, baseline='Offline reproduction of the deployed audio-packet gate and full lower-face blending.',
                  audio_delivery='Continuous cached PCM including natural pauses; same speech and timeline for all variants.',
                  synthetic_network_gaps=False, production_deployed=False)
    (OUTPUT / 'render-report.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
