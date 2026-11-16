"""Retain initial mux and package all rendered frames without re-running the model."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ffmpeg = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
for name in ['preview-v1', 'preview-fp16-v2']:
    directory = ROOT / 'outputs' / name
    target = directory / 'presenter-speaking-complete.mp4'
    subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                    '-i', str(directory / 'silent.mp4'), '-i', str(directory / 'driving-audio.wav'),
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-crf', '18',
                    '-preset', 'medium', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
                    '-metadata', 'comment=AI-generated presenter; local Wav2Lip technical preview',
                    str(target)], check=True)
    report_path = directory / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    # Original output remains available at report['output'].
    report['delivered_output'] = str(target)
    report['mux_note'] = 'Retained all 411 video frames; initial -shortest mux dropped the final frame. Initial mux preserved.'
    report['timing_scope'] = 'Measured inference loop with frame reads, compositing and intermediate encoding; excludes avatar preparation, warmup and final H264/AAC encoding.'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(name, target.stat().st_size)
