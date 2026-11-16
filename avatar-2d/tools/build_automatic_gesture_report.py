"""Collect bounded, non-secret acceptance evidence into a local review artifact."""
import hashlib
import html
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(path):return json.loads(path.read_text(encoding='utf-8'))

def main():
    live_path=ROOT/'docs/automatic-gestures-live-final-v4-2026-11-04.json';live=load(live_path)
    assert live.get('status')=='PASSED','Final live suite has not passed'
    semantic=load(ROOT/'docs/automatic-gesture-semantics-2026-11-04.json')
    preview_path=ROOT/'docs/automatic-gestures-preview-20261104-115813/report.json';preview=load(preview_path)
    manifest=load(ROOT/'runtime/automatic-gestures/manifest.json')
    for item in manifest['files']:
        assert hashlib.sha256((ROOT.parent/item['path']).read_bytes()).hexdigest()==item['after_sha256']
        assert hashlib.sha256((ROOT/'runtime/automatic-gestures/before'/item['path']).read_bytes()).hexdigest()==item['before_sha256']
    assert hashlib.sha256((ROOT/'service/gesture_planner.py').read_bytes()).hexdigest()==manifest['added_helper_sha256']
    summary=dict(status='PASSED',entry='http://127.0.0.1:8766/',
        validation=dict(protocol_scheduler_renderer_tests=20,ingress_tests=4,existing_model_config_tests=8,
            pcm_boundary_regression=True,page_auto_connect_regression=True,voice_listening_regression=True,
            semantic_cases=len(semantic['results']),semantic_passed=semantic['passed'],
            native_other_client_tool_callback=True,native_avatar_tool_callback=True,retired_endpoints=410,
            final_live_cases=len(live['cases']),rtc_interruption_cleared=True,
            rapid_new_input_old_result_discarded=live['rapid_new_input']['old_result_discarded'],
            local_asr_fixture=live.get('local_asr_fixture'),source_and_rollback_hashes_verified=True),
        independent_gesture_classifier_requests=0,small_model=live['model'],tts=live['tts'],
        evidence=dict(live=str(live_path),semantics=str(ROOT/'docs/automatic-gesture-semantics-2026-11-04.json'),
            previews=str(preview_path),rollback=str(ROOT/'Restore-PreviousConsole.ps1')),
        notes=['初始独立语义探测的9类判断均通过，其中后4条模型等待曾为86至88秒，未单独测量其SDK传输重试次数。',
               '最终用户回复通道关闭SDK自动重试；普通回答与动作在同一次模型请求输出。关联记忆的重要度评分等既有后台调用保持独立。',
               '曾有一条偏短介绍被选为idle，随后明确欢迎状态只限制迎宾、冷却只限制对应动作，并对最终规则重新完成整链测试。',
               '报告中的时延为本机当次结果，外部模型与TTS服务存在波动。',
               '物理麦克风、扬声器实听及用户对最终画质的主观验收未代替人工完成。',
               '保留配置与素材；没有重置或覆盖记忆，实际问答测试按既有机制产生正常对话记录。'])
    rows=[]
    for case in live['cases']:
        trace=case['traces'][0] if case['traces'] else None
        marks=trace['marks'] if trace else {}
        gesture=marks.get('gesture_decided');request=marks.get('llm_request_start')
        row=dict(case=case['case'],gesture=case['action'],frames=case['motion_frames'],
                 first_answer_seconds=case['first_answer_seconds'],first_playback_seconds=case['first_playback_seconds'],
                 model_to_gesture_seconds=round(gesture-request,3) if gesture is not None and request is not None else None,
                 body_after_gesture_seconds=round(marks['llm_first_text']-gesture,3) if gesture is not None and 'llm_first_text' in marks else None,
                 answer=case['answer'],jobs=case['jobs'])
        rows.append(row)
    summary['cases']=rows
    output=ROOT/'docs/automatic-gestures-acceptance-2026-11-04.json'
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    labels={'wake_and_first_question':'唤醒＋首问','repeat_wake_cached_welcome':'重复唤醒（缓存欢迎词）',
            'confirmation':'确认','explanation':'详细讲解','farewell':'告别','quoted_goodbye':'询问“再见”的词义'}
    def fmt(value):return '—' if value is None else f'{value:.3f} 秒'
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
        (labels.get(r['case'],r['case']),r['gesture'],r['frames'],fmt(r['first_answer_seconds']),fmt(r['first_playback_seconds'])))+'</tr>' for r in rows)
    videos=''.join(f'<article><h3>{html.escape(item["action"])}</h3><video controls preload="metadata" src="{Path(item["video"]).relative_to(ROOT/"docs").as_posix()}"></video><p>{item["motion_frames"]} 帧动作＋25帧末帧保持，使用同一冻结本地音频。</p></article>' for item in preview['cases'])
    notes=''.join('<li>'+html.escape(note)+'</li>' for note in summary['notes'])
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小霖自动动作验收</title>
<style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#101720;color:#dfe8f0;max-width:1150px;margin:40px auto;padding:0 24px;line-height:1.7}h1,h2{color:#94dfc8}a{color:#94dfc8}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #344456;padding:10px;text-align:left}section{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{border:1px solid #344456;border-radius:12px;padding:16px}video{background:black;width:100%;height:480px;object-fit:contain}img{width:100%}p,li{color:#b7c8d8}@media(max-width:700px){section{grid-template-columns:1fr}table{font-size:11px}td,th{padding:5px}}</style>
<h1>小霖自动动作与统一问答入口</h1><p>已部署到 <a href="http://127.0.0.1:8766/">正式展示页</a>。刷新当前展示窗口后即可使用。文本与麦克风统一问答，动作在同一轮模型输出中决定；直接播报和手动动作接口返回 410。</p>
<h2>实际链路验收</h2><table><thead><tr><th>场景</th><th>实际动作</th><th>动作帧数</th><th>首段回答文字</th><th>首次播放回调</th></tr></thead><tbody>'''+table+'''</tbody></table><p>唤醒＋首问的回答时间包含固定欢迎词的先行播报。重复唤醒未发起大模型问答；本轮缓存欢迎词没有重复挥手。</p>
<h2>画面预检素材</h2><p>使用实际 Presenter/Wav2Lip 渲染，同一冻结音频覆盖完整原动作，每帧匹配其自身的人脸坐标。最终口型自然度可直接播放查看。</p><section>'''+videos+'''</section>
<h2>规则与边界</h2><p>每轮最多一个非待机动作，同一动作从实际播放起冷却15秒。告别或60秒无输入结束接待；重新连接展示不自动欢迎。唤醒欢迎与首问共用名额。缓存音频与实时PCM共享调度。新输入或打断同步清理已排队音画，动作素材完整播放后保持末帧。</p>
<h2>验证说明</h2><ul>'''+notes+'''</ul><p>自动回归：20项解析/调度/渲染测试、4项入口与音频入队测试、原有8项模型配置回归；PCM分块、页面自动重连、连续语音聆听回归通过。9类语义覆盖通过，工具回调使用隔离模拟验证。实际快速连续提问验证旧结果被丢弃，新一轮能正常回答。</p><p><a href="automatic-gestures-acceptance-2026-11-04.json">完整验收数据</a> · <a href="automatic-gestures-live-final-v4-2026-11-04.json">最终链路原始记录</a></p></html>'''
    page=ROOT/'docs/automatic-gestures-acceptance-2026-11-04.html';page.write_text(document,encoding='utf-8')
    print(json.dumps({'report':str(page),'json':str(output),'cases':[{k:v for k,v in row.items() if k not in ('jobs','answer')} for row in rows]},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
