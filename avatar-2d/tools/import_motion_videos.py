"""Preserve supplied motion videos, decode them, and build visual inspection sheets."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets/presenter-v1/motions-v1'
FFBIN = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin'


def save(path, image):
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError('Image encoding failed')
    path.write_bytes(encoded.tobytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-id', action='append')
    args = parser.parse_args()
    keys = args.source_id or ['6386', '8571', '8580', '8687']
    if any(not key.isdecimal() for key in keys):
        raise ValueError('Source IDs must be numeric')
    reports = []
    for key in keys:
        matches = list((Path.home() / 'Downloads').glob(f'jimeng-2026-11-03-{key}-*.mp4'))
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one supplied file for {key}, found {len(matches)}')
        source = matches[0]
        directory = DEST / ('incoming-' + key)
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / 'source.mp4'
        shutil.copy2(source, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != hashlib.sha256(source.read_bytes()).hexdigest():
            raise RuntimeError('Source copy hash mismatch')
        probe = subprocess.run([str(FFBIN / 'ffprobe.exe'), '-v', 'error', '-show_streams',
                                '-show_format', '-of', 'json', str(target)],
                               check=True, capture_output=True, encoding='utf-8')
        metadata = json.loads(probe.stdout)
        (directory / 'source-ffprobe.json').write_text(probe.stdout, encoding='utf-8')
        stream = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
        capture = cv2.VideoCapture(str(target))
        expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        indices = np.linspace(0, expected - 1, 8).round().astype(int).tolist()
        full_tiles, face_tiles, samples = [], [], []
        count = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if count in indices:
                seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                save(directory / f'frame-{count:04d}.jpg', frame)
                tile = cv2.resize(frame, (200, 356))
                cv2.putText(tile, f'{seconds:.2f}s / {count}', (6, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, .46, (0, 255, 255), 1, cv2.LINE_AA)
                full_tiles.append(tile)
                h, w = frame.shape[:2]
                head = frame[int(h*.025):int(h*.24), int(w*.32):int(w*.68)]
                face_tile = cv2.resize(head, (240, 260))
                cv2.putText(face_tile, f'{seconds:.2f}s', (5, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 255), 1, cv2.LINE_AA)
                face_tiles.append(face_tile)
                samples.append(dict(frame=count, seconds=seconds))
            count += 1
        capture.release()
        if count != expected or len(full_tiles) != 8:
            raise RuntimeError(f'Incomplete decode {key}: {count}/{expected}')
        subprocess.run([str(FFBIN / 'ffmpeg.exe'), '-hide_banner', '-v', 'error', '-xerror',
                        '-i', str(target), '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], check=True)
        save(directory / 'fullbody-contact-sheet.jpg', np.vstack([np.hstack(full_tiles[:4]), np.hstack(full_tiles[4:])]))
        save(directory / 'face-contact-sheet.jpg', np.vstack([np.hstack(face_tiles[:4]), np.hstack(face_tiles[4:])]))
        report = dict(source_id=key, original_path=str(source), retained_path=str(target),
                      sha256=digest, bytes=target.stat().st_size, decoded_frames=count,
                      width=stream['width'], height=stream['height'],
                      average_frame_rate=stream['avg_frame_rate'], nominal_frame_rate=stream['r_frame_rate'],
                      video_seconds=float(stream['duration']),
                      audio_present=any(s['codec_type'] == 'audio' for s in metadata['streams']),
                      strict_decode_passed=True, samples=samples, action='AWAITING_VISUAL_CLASSIFICATION')
        (directory / 'inspection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        reports.append(report)
        print(json.dumps({k: v for k, v in report.items() if k not in ['original_path', 'retained_path', 'samples']}, ensure_ascii=False), flush=True)
    report_name = 'import-report-'+'-'.join(keys)+'.json' if args.source_id else 'import-report.json'
    (DEST / report_name).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
