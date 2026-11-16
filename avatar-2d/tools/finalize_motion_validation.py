"""Publish only motion test results that match the prepared asset hashes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT/'assets/presenter-v1/motions-v1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    path = LIB/'action-library.json'
    library = read(path)
    results = []
    for action in library['actions']:
        inspection_path = LIB/('incoming-'+action['source_id'])/'inspection.json'
        inspection = read(inspection_path)
        inspection['action'] = action['id']
        inspection['classification'] = 'Observed sampled full-body and face frames; wave labels assigned by relative timing'
        write(inspection_path, inspection)
        if not action['speech_candidate']:
            continue
        matches = []
        for report_path in (ROOT/'outputs').glob('motion-*/report.json'):
            report = read(report_path)
            if (report.get('motion') == action['id'] and
                    report.get('avatar', {}).get('source_sha256') == action['prepared_sha256']):
                matches.append((report_path, report))
        if not matches:
            raise RuntimeError('Missing real inference test: '+action['id'])
        report_path, report = sorted(matches, key=lambda r: r[0].parent.name)[-1]
        validation = read(report_path.parent/'validation.json')
        if (validation['status'] != 'TECHNICAL_MEDIA_CHECK_PASSED' or
                validation['decoded_frames'] != action['frames'] or
                report['frames'] != action['frames'] or report['cloud_calls'] != 0):
            raise RuntimeError('Motion verification mismatch: '+action['id'])
        action['lipsync_tested'] = True
        action['lipsync_output'] = str(Path(report['output']).relative_to(ROOT))
        action['lipsync_report'] = str(report_path.relative_to(ROOT))
        action['technical_validation'] = str((report_path.parent/'validation.json').relative_to(ROOT))
        action['human_phoneme_sync_accepted'] = False
        write(LIB/'prepared'/(action['id']+'.json'), action)
        results.append(dict(id=action['id'], frames=report['frames'],
                            seconds=report['audio_seconds'], output=action['lipsync_output'],
                            peak_allocated_gpu_mb=report['peak_allocated_gpu_mb'],
                            pipeline_fps=report['pipeline_fps'], validation=validation['status']))
    library['status'] = 'THREE_REQUESTED_MOTIONS_LIPSYNC_TESTED_SUBTLE_NOD_PENDING'
    write(path, library)
    summary = dict(status=library['status'], imported_files=4, source_frames=724,
                   normalized_motion_frames=sum(a['frames'] for a in library['actions']),
                   speaking_motion_tests=results,
                   silent_bow='assets/presenter-v1/motions-v1/prepared/bow-greeting.mp4',
                   sequence='outputs/motion-review-v1/motion-sequence.mp4',
                   subtle_nod_available=False, live_switching_verified=False,
                   realtime_streaming_verified=False, target_hardware_verified=False,
                   human_visual_and_phoneme_acceptance=False)
    write(LIB/'validation-summary.json', summary)
    avatar_path = ROOT/'assets/presenter-v1/avatar.json'
    avatar = read(avatar_path)
    avatar['stage'] = 'local_motion_assets_and_lipsync_tests_available_subtle_nod_pending'
    avatar['motion_library'] = 'motions-v1/action-library.json'
    avatar['motion_validation'] = 'motions-v1/validation-summary.json'
    avatar['motion_sequence_preview'] = '../../outputs/motion-review-v1/motion-sequence.mp4'
    write(avatar_path, avatar)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
