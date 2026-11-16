"""Decode delivered media and retain a sample sheet for human inspection."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    args = parser.parse_args()
    directory = ROOT / 'outputs' / args.output
    run = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    video = Path(run.get('delivered_output', directory / 'presenter-speaking.mp4'))
    ffbin = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin'
    probe = subprocess.run([str(ffbin / 'ffprobe.exe'), '-v', 'error', '-show_streams',
                            '-show_format', '-of', 'json', str(video)],
                           check=True, capture_output=True, encoding='utf-8')
    metadata = json.loads(probe.stdout)
    (directory / 'ffprobe.json').write_text(probe.stdout, encoding='utf-8')
    # Decode both streams with strict FFmpeg error handling, then independently count video frames.
    subprocess.run([str(ffbin / 'ffmpeg.exe'), '-hide_banner', '-v', 'error', '-xerror',
                    '-i', str(video), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], check=True)
    capture = cv2.VideoCapture(str(video))
    count = 0
    shapes = set()
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        count += 1
        shapes.add(tuple(frame.shape))
    capture.release()
    if count != run['frames'] or shapes != {(1280, 720, 3)}:
        raise RuntimeError(f'Unexpected decoded frames: {count}, shapes: {shapes}')
    streams = metadata['streams']
    v = next(s for s in streams if s['codec_type'] == 'video')
    a = next(s for s in streams if s['codec_type'] == 'audio')
    if v['avg_frame_rate'] != '25/1' or v['codec_name'] != 'h264' or a['codec_name'] != 'aac':
        raise RuntimeError('Unexpected output encoding')
    av_delta = abs(float(v['duration']) - float(a['duration']))
    if av_delta > 0.08:
        raise RuntimeError(f'Unexpected stream duration difference: {av_delta}')
    # Enlarged sampled faces support visual review; they are not an objective lip-sync score.
    tiles = []
    for i in run['saved_frames']:
        face_path = directory / f'face-{i:04d}.png'
        face = cv2.imdecode(np.frombuffer(face_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        tile = np.full((330, 250, 3), 28, dtype=np.uint8)
        resized = cv2.resize(face, (190, 262), interpolation=cv2.INTER_CUBIC)
        tile[15:277, 30:220] = resized
        cv2.putText(tile, f'{i/25:.2f}s / frame {i}', (15, 312), cv2.FONT_HERSHEY_SIMPLEX,
                    .52, (235, 235, 235), 1, cv2.LINE_AA)
        tiles.append(tile)
    while len(tiles) % 4:
        tiles.append(np.full_like(tiles[0], 28))
    sheet = np.vstack([np.hstack(tiles[i:i+4]) for i in range(0, len(tiles), 4)])
    ok, jpg = cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise RuntimeError('Could not encode sample sheet')
    (directory / 'face-contact-sheet.jpg').write_bytes(jpg.tobytes())
    validation = dict(status='TECHNICAL_MEDIA_CHECK_PASSED', decoded_frames=count,
                      width=720, height=1280, fps=25, video_codec=v['codec_name'],
                      audio_codec=a['codec_name'], audio_sample_rate=int(a['sample_rate']),
                      video_seconds=float(v['duration']), audio_seconds=float(a['duration']),
                      duration_difference_seconds=av_delta,
                      ffmpeg_strict_audio_video_decode=True,
                      sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                      human_phoneme_sync_accepted=False, realtime_streaming_tested=False)
    (directory / 'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    print(json.dumps(validation))


if __name__ == '__main__':
    main()
