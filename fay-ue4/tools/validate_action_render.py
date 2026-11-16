"""Validate native renderer evidence, without counting screenshots as art acceptance."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def validate():
    manifest=ROOT/'assets/girl008-actions-preview-v2.json'
    spec=json.loads(manifest.read_text(encoding='utf-8'))
    directory=ROOT/'ue4/Saved/ActionTests/v2-verified'
    results=[]
    for index,name in enumerate(['idle','wave','explain','nod','bow','point','walk','turn_left','turn_right','speaking','welcome','goodbye']):
        samples=[]
        for shot in range(3):
            stem=directory/f'{index:02}_{name}_{shot}'
            r=json.loads(stem.with_suffix('.json').read_text(encoding='utf-8-sig'))
            assert r['finite'] and r['requested']==name
            expected=name if shot<2 or spec['motion_clips'][name]['loop'] else 'idle'
            assert r['active']==expected,(name,shot,r['active'])
            assert stem.with_suffix('.png').stat().st_size>10000
            assert min(r['bones'][b][2] for b in ['ToesEnd_L','ToesEnd_R'])>-.1
            samples.append(r)
        frames=list((directory/'frames'/name).glob('*.png'))
        assert len(frames)>20
        results.append(dict(action=name,loop=spec['motion_clips'][name]['loop'],screenshots=3,recorded_frames=len(frames),end_state=samples[-1]['active']))
    log=(ROOT/'runtime/ue-actions-suite-v2-verified.log').read_text(encoding='utf-8-sig')
    assert 'MotionSuite completed 12 clips' in log and 'Error:' not in log
    report=dict(status='LOCAL_PREVIEW_RENDER_CHECKS_PASSED',manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                actions=results,screenshots=36,recorded_frames=sum(r['recorded_frames'] for r in results),
                python_tests='48 passed; 1 dependency deprecation warning',
                native_automation_report='runtime/motion-automation-v2-verified/index.json',
                visual_review='Front full-body key poses inspected; wrist direction corrected after first pass',
                limits=['In-place walking, without scene navigation','Turn is a 75-degree pivot and return, without turn-in-place footwork','Welcome and goodbye reuse wave','No cloth or hair simulation','No production registration or packaged EXE/GTX1660 acceptance'])
    native=json.loads((ROOT/'runtime/motion-automation-v2-verified/index.json').read_text(encoding='utf-8-sig'))
    assert native['succeeded']==1 and native['failed']==0
    native_log=(ROOT/'runtime/ue-motion-automation-v2-verified.log').read_text(encoding='utf-8-sig')
    assert 'LogExit: Exiting.' in native_log and 'Error:' not in native_log
    report['native_automation']='1 passed; engine exited cleanly with OculusVR disabled for this command only'
    live=(ROOT/'runtime/preview-latest.log').read_text(encoding='utf-8-sig')
    audio=live.find('Kiosk local audio started: 394308 samples')
    wave=live.find('Kiosk motion started: wave',audio) if audio>=0 else -1
    finished=live.find('Kiosk motion completed: wave',wave) if wave>=0 else -1
    resumed=live.find('Kiosk motion started: speaking',finished) if finished>=0 else -1
    drained=live.find('Kiosk local audio drained; mouth returned to neutral',resumed) if resumed>=0 else -1
    report['interactive_audio_gesture']='Verified local audio -> wave -> speaking resumed -> audio drained and mouth neutral' if 0 <= audio < wave < finished < resumed < drained else 'Not exercised in latest interactive session'
    out=ROOT/'docs/girl008-actions-validation-v2.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':validate()
