"""Verify identical inputs/poses, combine videos, retain human visual acceptance."""
import hashlib
import html
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'


def main():
    def read(path):return json.loads(path.read_text(encoding='utf-8'))
    baseline=read(ROOT/'outputs/wav2lip-offline.json');candidate=read(ROOT/'outputs/musetalk-offline.json')
    target=ROOT/'outputs/comparisons';target.mkdir(exist_ok=True)
    files=[];checks=[]
    for a,b in zip(baseline['cases'],candidate['cases']):
        assert (a['action'],a['fixture'])==(b['action'],b['fixture'])
        assert a['fixture_sha256']==b['fixture_sha256'] and a['pose_sha256']==b['pose_sha256'],(a,b)
        assert a['frames']==b['frames'] and a['body_below_face_unchanged'] and b['body_below_face_unchanged']
        checks.append({'action':a['action'],'fixture':a['fixture'],'frames':a['frames'],'same_pose_timeline':True,'same_audio':True,'body_unchanged':True})
        for view in ['full','mouth']:
            destination=target/(a['action']+'-'+a['fixture']+'-'+view+'.mp4')
            if not destination.exists():
                font="C\\:/Windows/Fonts/arial.ttf"
                size=32 if view=='full' else 20
                graph=f"[0:v]drawtext=fontfile='{font}':text='Wav2Lip':x=16:y=16:fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.6[a];[1:v]drawtext=fontfile='{font}':text='MuseTalk 1.5':x=16:y=16:fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.6[b];[a][b]hstack=inputs=2[v]"
                subprocess.run([str(FFMPEG),'-v','error','-nostdin','-n','-i',str(ROOT/a[view]),'-i',str(ROOT/b[view]),
                    '-filter_complex',graph,'-map','[v]','-map','0:a','-c:v','libx264','-threads','2','-preset','veryfast',
                    '-crf','18','-pix_fmt','yuv420p','-c:a','copy','-shortest',str(destination)],check=True,timeout=90)
            files.append({'action':a['action'],'fixture':a['fixture'],'view':view,'file':str(destination.relative_to(ROOT)),
                'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'left':'wav2lip','right':'musetalk'})
            print('COMPARISON',destination.name,flush=True)
    report={'status':'OFFLINE_COMPARISONS_COMPLETE','fixture_manifest':read(ROOT/'fixtures/manifest.json'),
        'first_preparation':read(ROOT/'docs/first-preparation-observed.json'),
        'offline':{'wav2lip':baseline,'musetalk':candidate},'asset_checks':checks,'comparisons':files,
        'visual_acceptance':'USER_REVIEW_REQUIRED','default_backend_changed':False,'cloud_calls':0}
    if (ROOT/'outputs/realtime-validation.json').exists():report['realtime']=read(ROOT/'outputs/realtime-validation.json')
    if report.get('realtime',{}).get('status')=='REAL_WEBRTC_EVALUATION_COMPLETE':
        report['status']='TECHNICAL_EVALUATION_COMPLETE_VISUAL_REVIEW_REQUIRED'
    (ROOT/'outputs/evaluation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    realtime=report.get('realtime',{})
    rows=''.join('<tr><td>'+x['backend']+'</td><td>'+f"{x['received_fps']:.2f}"+'</td><td>'+f"{x['p95_first_video_seconds']*1000:.0f} ms"+'</td><td>'+f"{x['gpu_peak_mb']:.0f} MiB"+'</td><td>'+str(x['queue_max'])+'</td><td>'+f"{x['duration_seconds']:.1f} s"+'</td></tr>' for x in realtime.get('results',[]))
    labels={'idle':'待机说话','welcome-wave':'迎宾挥手','goodbye-wave':'告别挥手','explain-open-palms':'摊手讲解','acknowledge-nod':'点头'}
    videos=''
    for fixture,fixture_label in [("long","长语音"),("short","短语音")]:
        for action,label in labels.items():
            videos+=f'<section><h2>{label} · {fixture_label}</h2><p>左：Wav2Lip　右：MuseTalk 1.5</p><div class="videos">'
            for view,text in [('full','全身'),('mouth','面部放大')]:
                videos+=f'<div><h3>{text}</h3><video controls preload="none" src="comparisons/{html.escape(action)}-{fixture}-{view}.mp4"></video></div>'
            videos+='</div></section>'
    verdict='性能未达标，保留正式 Wav2Lip' if realtime.get('performance_pass') is False else '性能检查完成，画质待人工确认' if realtime.get('performance_pass') else '实时测试正在进行，画质待人工确认'
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小霖口型后端评估报告</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;background:#121b26;color:#e6edf5;max-width:1280px;margin:auto;padding:28px}h1{font-size:28px}h2{font-size:22px}h3{font-size:17px}section{padding:20px;background:#1e2b3a;border:1px solid #3a4b5f;border-radius:12px;margin:22px 0}.badge{color:#ffc181}a{color:#77c7ed}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #435064;padding:12px}video{width:100%;max-height:630px;background:black}.videos{display:grid;grid-template-columns:1fr 1fr;gap:20px}.small{color:#a9b8c8;font-size:14px}@media(max-width:700px){.videos{grid-template-columns:1fr}table{font-size:12px}th,td{padding:6px}body{padding:14px}}</style><h1>小霖 · 口型后端评估报告</h1>'''
    document+=f'<p class="badge">{verdict}；人物与逐音素口型仍需观看确认。</p><p><a href="/">返回实时预览</a> · <a href="evaluation-report.json">完整 JSON 数据</a></p>'
    document+='<section><h2>真实 WebRTC 实测</h2><table><tr><th>后端</th><th>实收 fps</th><th>首帧 P95</th><th>PyTorch 峰值</th><th>峰值积压帧</th><th>持续时长</th></tr>'+rows+'</table><p class="small">首帧从提交固定 PCM 播放请求计到首个生成口型帧，不包含 ASR、LLM、TTS 前置等待；显存为实验进程 PyTorch 分配峰值。20 ms 为一个音频队列帧。两个后端顺序测量，每个至少 300 秒。</p></section>'
    document+='<section><h2>素材一致性与加载</h2><p>同一小霖，四动作共 675 帧；10 组输入条件的音频摘要、姿态帧时间轴完全一致，脸部下方身体区域保持原像素。已生成 20 个左右对照视频，未更改正式后端。</p><p>首次模型加载约 22.05 秒，首次动作缓存预处理约 70.34 秒，含预热整体就绪约 95.73 秒。后续启动复用缓存，加载时间见 JSON。</p><p class="small">点头沿用现有早段剪辑候选，其原素材的人工验收状态不会被本次自动检查覆盖。视频为 25 fps 导出；导出帧率不能代表实时推理速度，请以实收 fps 为准。</p></section>'+videos+'</html>'
    (ROOT/'outputs/report.html').write_text(document,encoding='utf-8')
    print(report['status'],flush=True)


if __name__=='__main__':main()
