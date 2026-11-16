"""Join the checked A/C comparisons and retain their independent results."""
import json
import subprocess
from pathlib import Path

output = Path('/formal/smile-other-actions-20261111')
assert (output / 'complete').exists()
actions = ['goodbye-wave', 'explain-open-palms', 'acknowledge-nod']
args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
filters = []
records = []
total_frames = 0
for index, action in enumerate(actions):
    directory = output / action
    report = json.loads((directory / 'render-report.json').read_text())
    verification = json.loads((directory / 'verification.json').read_text())
    assert verification['status'] == 'PASSED'
    args += ['-threads', '2', '-i', str(directory / report['comparison_file'])]
    filters += [f'[{index}:v]setpts=PTS-STARTPTS[v{index}]',
                f'[{index}:a]atrim=duration={report["seconds"]},asetpts=PTS-STARTPTS[a{index}]']
    records.append(dict(action=action, start_seconds=total_frames / 50,
                        seconds=report['seconds'], frames=report['frames'],
                        landmark_frames=report['landmark_frames'],
                        landmark_detection_failures=report['landmark_detection_failures'],
                        fallback_frames=report['fallback_frames'],
                        decoded_audio_identical=verification['decoded_audio_identical']))
    total_frames += report['frames']
filters.append(''.join(f'[v{index}][a{index}]' for index in range(3)) + 'concat=n=3:v=1:a=1[v][a]')
target = output / 'all-actions-AC-comparison-50fps.mp4'
args += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-r', '50',
         '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-threads', '2', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', str(target)]
subprocess.run(args, check=True)
result = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
                    '-show_entries', 'stream=codec_type,width,height,nb_read_frames,avg_frame_rate,duration',
                    '-of', 'json', str(target)], text=True))
video = next(stream for stream in result['streams'] if stream['codec_type'] == 'video')
assert int(video['nb_read_frames']) == total_frames
assert video['avg_frame_rate'] == '50/1'
assert (video['width'], video['height']) == (768, 1202)
summary = dict(status='PASSED', fps=50, combined_frames=total_frames,
               combined_seconds=total_frames / 50, actions=records,
               speech=json.loads(Path('/formal/smile-review-20261111/audio.json').read_text()),
               production_deployed=False)
(output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(summary, ensure_ascii=False), flush=True)
