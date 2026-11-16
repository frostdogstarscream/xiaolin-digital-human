import argparse
import hashlib
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('/formal/smile-review-20261111'))
args = parser.parse_args()
output = args.output
report = json.loads((output / 'render-report.json').read_text())
files = report.get('output_files', ['A-current-50fps.mp4', 'B-sentence-fade-50fps.mp4', 'C-lip-landmarks-50fps.mp4',
                                  'ABC-audible-comparison-50fps.mp4'])
records = []
hashes = set()
for name in files:
    path = output / name
    result = subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-show_entries',
        'stream=codec_type,width,height,avg_frame_rate,nb_read_frames,duration,sample_rate,channels',
        '-of', 'json', str(path)], text=True)
    streams = json.loads(result)['streams']
    video = next(stream for stream in streams if stream['codec_type'] == 'video')
    audio = next(stream for stream in streams if stream['codec_type'] == 'audio')
    assert video['avg_frame_rate'] == '50/1'
    assert int(video['nb_read_frames']) == report['frames']
    comparison_size = (report.get('comparison_width', 1152), 1202)
    assert (video['width'], video['height']) == (comparison_size if 'comparison' in name else (1080, 1920))
    assert int(audio['channels']) == 1 and int(audio['sample_rate']) == 16000
    assert abs(float(video['duration']) - report['seconds']) < .021
    pcm = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-threads', '2',
                                   '-i', str(path), '-map', '0:a:0', '-f', 's16le', '-ac', '1', '-ar', '16000', '-'])
    digest = hashlib.sha256(pcm).hexdigest()
    hashes.add(digest)
    records.append(dict(file=name, frames=int(video['nb_read_frames']), fps=50,
                        width=video['width'], height=video['height'], seconds=float(video['duration']),
                        decoded_audio_sha256=digest, bytes=path.stat().st_size))
    print('VERIFIED', name, flush=True)
assert len(hashes) == 1, 'The decoded comparison audio differs between variants'
assert report['landmark_frames'] > 0
assert not report['fallback_frames'], report['fallback_frames']
verification = dict(status='PASSED', decoded_audio_identical=True, videos=records,
                    landmark_detection_failures=report['landmark_detection_failures'])
(output / 'verification.json').write_text(json.dumps(verification, indent=2))
print(json.dumps(verification), flush=True)
