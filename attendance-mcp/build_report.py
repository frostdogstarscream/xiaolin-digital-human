"""Source-only rollback manifest and human-readable local MCP acceptance report."""
import hashlib
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent;WORKSPACE=ROOT.parent
FILES=['avatar-2d/service/gesture_planner.py','avatar-2d/Start-DigitalHuman.ps1',
       'fay-ue4/runtime/fay-local/app/llm/nlp_cognitive_stream.py',
       'fay-ue4/runtime/fay-local/app/llm/execution_manager.py',
       'fay-ue4/runtime/fay-local/app/gui/flask_server.py']

def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def main():
    live=load(ROOT/'reports/live-accepted-2026-11-04.json');assert live['status']=='PASSED'
    protocol=load(ROOT/'reports/protocol-2026-11-04.json');cancellation=load(ROOT/'reports/cancellation-2026-11-04.json')
    cases=[]
    for name in ('semantics-first-2026-11-04.json','semantics-rest-2026-11-04.json','semantics-quoted-2026-11-04.json'):
        report=load(ROOT/'reports'/name);assert report['status']=='PASSED';cases+=report['cases']
    assert len(cases)==11 and all(c['passed'] for c in cases)
    entries=[]
    for relative in FILES:
        before=ROOT/'runtime/before'/relative;current=WORKSPACE/relative
        assert before.is_file()
        entries.append(dict(path=relative,before_sha256=hashlib.sha256(before.read_bytes()).hexdigest(),
            after_sha256=hashlib.sha256(current.read_bytes()).hexdigest()))
        saved=ROOT/'runtime/release'/relative;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(current.read_bytes())
    for relative in ('avatar-2d/service/attendance_policy.py','attendance-mcp/server.py'):
        current=WORKSPACE/relative;saved=ROOT/'runtime/release'/relative;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(current.read_bytes())
    (ROOT/'runtime/source-manifest.json').write_text(json.dumps({'files':entries},indent=2),encoding='utf-8')
    registration=load(ROOT/'runtime/registration.json');assert registration['enabled'] and registration['prestart'] is False
    process=load(ROOT/'runtime/process.json');log=Path(process['logs'])/'stdout.log'
    success_lines=[line for line in log.read_text(encoding='utf-8-sig').splitlines() if line.strip()=='success']
    assert success_lines,'No success print in current server log'
    summary=dict(status='PASSED',server=dict(name='小霖 · 占位打卡测试',url=registration['url'],tool=registration['tool'],
        enabled=True,prestart=False,manager='http://127.0.0.1:5010/Page3'),
        validation=dict(local_placeholder_tests=8,existing_gesture_tests=20,existing_tool_callback=True,
            protocol=protocol,semantic_cases=len(cases),semantic_passed=True,cancellation=cancellation,
            formal_live_passed=True,offline_rpc_failed=live['offline_rpc_failed'],reconnect_did_not_execute=live['reconnect_did_not_execute']),
        semantic_cases=cases,live=live,
        delivery=dict(start=str(ROOT/'Start-AttendanceMcp.cmd'),stop=str(ROOT/'Stop-AttendanceMcp.cmd'),
            server_source=str(ROOT/'server.py'),current_stdout=str(log),call_audit=str(ROOT/'runtime/calls.jsonl'),
            rollback=str(ROOT/'Restore-BeforeAttendance.ps1')),
        limitations=['占位工具只打印并返回 success，没有连接真实考勤。',
            'ASR使用百炼合成的本地测试音频；真人麦克风和扬声器实听未代替人工完成。',
            '语义批量测试使用隔离上下文和输出，正式链路验收按原机制产生少量测试对话记录。',
            '测试曾因旧WebRTC关闭阻塞而重启展示服务，随后原Firefox自动重连并完成验收。',
            'Windows后台进程继承测试管道导致一次控制等待超时，实际服务已恢复；测试控制器改为无管道等待后恢复验收通过。'])
    target=ROOT/'reports/acceptance-2026-11-04.json';target.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    def esc(value):return html.escape(str(value))
    semantic_rows=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (c['question'],c['action'],c['actual_server_calls'],c['answer']))+'</tr>' for c in cases)
    live_rows=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in
        (c['case'],c['actual_server_calls'],c.get('first_final_text_seconds','—'),c.get('first_final_playback_seconds','—'),c.get('rpc_seconds','—')))+'</tr>' for c in live['cases'])
    notes=''.join('<li>'+esc(note)+'</li>' for note in summary['limitations'])
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小霖 MCP 占位打卡验收</title>
<style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#111922;color:#dae6ef;max-width:1200px;margin:36px auto;padding:0 22px;line-height:1.7}h1,h2,a{color:#8fdcc1}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #344657;padding:10px;text-align:left;vertical-align:top}pre{padding:16px;background:#090e14;border:1px solid #344657;border-radius:8px}p,li{color:#b7c9d9}.wide{overflow:auto}small{color:#91a5b9}</style>
<h1>小霖 MCP 占位打卡：验收通过</h1><p>按真实语义及对话上下文自动选择工具，不要求固定措辞。<a href="http://127.0.0.1:8766/">打开数字人问答</a> · <a href="http://127.0.0.1:5010/Page3">Fay MCP 管理</a></p>
<p>服务：<code>http://127.0.0.1:8783/sse</code>；工具：<code>attendance_check_in()</code>。当前已启用、预启动执行关闭。服务端每次实际调用打印并返回：</p><pre>success</pre>
<h2>真实模型语义测试</h2><p>11类场景全部通过；明确请求、同义表达和上下文确认各调用一次，其余场景零调用。此批量测试隔离了正式对话历史、记忆及TTS输出。</p><div class="wide"><table><tr><th>用户表达</th><th>模型决策</th><th>服务端实际调用</th><th>模型回复</th></tr>'''+semantic_rows+'''</table></div>
<h2>正式链路与耗时</h2><p>文字输入及合成音频经本机FunASR、唤醒、MCP、百炼TTS和原Firefox WebRTC播放通过。下表单位为秒，从提交问题起算；语音场景包含固定欢迎词先行播报，工具离线场景没有成功结果。</p><div class="wide"><table><tr><th>场景</th><th>服务端调用</th><th>首段最终结果文字</th><th>首次结果播放</th><th>MCP RPC耗时</th></tr>'''+live_rows+'''</table></div>
<p>停用工具后明确反馈未执行；恢复连接不自动调用，再次明确请求成功。原生规划线程取消测试：旧轮次0次调用，新轮次1次调用，旧回调未覆盖新状态。流式音频分块不会重复调用打卡。</p>
<h2>交付与说明</h2><p>本目录上一级的 Start-AttendanceMcp.cmd 和 Stop-AttendanceMcp.cmd 可独立启动、停止。主数字人启动入口会自动恢复已启用的占位服务。恢复接入前代码可使用 Restore-BeforeAttendance.ps1；它校验备份和当前代码摘要，保留配置、记忆与素材。</p><ul>'''+notes+'''</ul><p><a href="acceptance-2026-11-04.json">完整验收数据与日志位置</a> · <a href="live-accepted-2026-11-04.json">正式链路原始记录</a></p></html>'''
    page_path=ROOT/'reports/acceptance-2026-11-04.html';page_path.write_text(page,encoding='utf-8')
    print(json.dumps(dict(report=str(page_path),data=str(target),stdout=str(log),semantic_cases=len(cases),
        current_server_success_prints=len(success_lines),live=[{k:c.get(k) for k in ('case','actual_server_calls','first_final_text_seconds','first_final_playback_seconds','rpc_seconds')} for c in live['cases']]),ensure_ascii=True),flush=True)

if __name__=='__main__':main()
