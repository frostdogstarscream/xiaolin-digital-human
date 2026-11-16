"""Package reviewed source and sanitized acceptance evidence, never runtime state or credentials."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'outputs' / 'qwen-realtime-v2'

def browser(name):
    raw = (OUT / name).read_text(encoding='utf-8-sig')
    result = json.loads(raw.split('### Result', 1)[1].split('### Ran', 1)[0].strip())
    assert result['status'] == 'PASSED', name
    return result

names = ['browser-retrieval-final.log', 'browser-switches-final.log',
         'browser-semantics-b-final.log', 'browser-voice-interrupt.log', 'browser-actions.log']
checks = {name: browser(name) for name in names}
for name in ['access-report.json', 'persistence-report.json']:
    checks[name] = json.loads((OUT / name).read_text())
    assert checks[name]['status'] == 'PASSED'
assert 'Ran 12 tests' in (OUT / 'unit-tests.log').read_text() and (OUT / 'unit-tests.log').read_text().rstrip().endswith('OK')
checks['unit_tests'] = {'status': 'PASSED', 'count': 12}
report = {
    'status': 'PASSED', 'date': '2026-11-10',
    'entry': 'https://36.133.88.94:6444/',
    'production_preserved': 'https://36.133.88.94:6443/',
    'model_tested': 'qwen-audio-3.1-realtime-flash',
    'model_configurable_not_tested': 'qwen-audio-3.1-realtime-plus',
    'defaults': checks['persistence-report.json']['settings'],
    'default_namespace': {'knowledge_fragments': 0, 'memory_records': 0},
    'coordination': 'Native function calling on demand; ordinary replies may answer directly. No separate intent-model request.',
    'memory_boundary': 'Independent v2 persistent vector memory; existing Fay Bionic memory and history were not migrated.',
    'test_namespace': 'acceptance-v2-20261110; test knowledge removed; test memories remain isolated',
    'no_host_reboot': True,
    'limitations': ['Real microphone/speaker and visual quality require human acceptance.',
                    'Business knowledge has not been supplied; text ingestion is available.',
                    'No new five-minute performance or Plus-model benchmark claimed.',
                    'Operational capability audit events are service-wide; knowledge and memory records are namespaced.'],
    'checks': checks,
    'historical_evidence': {'browser-semantics-b.log': 'Initial mandatory-function protocol failed smalltalk; fixed by on-demand coordination and retested in final log.',
                            'browser-semantics-a.log': 'Earlier semantic exclusion checks; no later change to tool intent policy.'}
}
(OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
guide = '''小霖实时语音与能力管理 v2 — 使用与验收说明
日期：2026-11-10

访问：https://36.133.88.94:6444/，沿用已有访问账号、HTTPS CA 与网络范围。
原 Fay 正式模式：https://36.133.88.94:6443/，保持原配置。

使用：打开“模型与能力”，选择模型，设置“模型能力协同总开关”及四个独立开关，点击“保存并应用”。保存会停止当前对话、清理旧轮次，下次提问使用新配置。默认五个开关全部开启。
当前实际验收模型：qwen-audio-3.1-realtime-flash，音色 longanqian_v3.1。
Plus 可配置但本次没有实际调用验收，不代表已验证效果或速度。

协同：模型可直接回答普通问题；需要业务能力时，通过同一实时模型的 coordinate_turn 原生工具调用规划 MCP、业务检索、记忆检索和手势。不是前端关键词匹配，也未添加独立意图分类模型请求。后台执行允许的能力并把真实结果返给模型，再生成语音与口型。关闭总开关时保留普通语音和口型，不执行这四项能力。

MCP：复用 Fay 已注册的 attendance_check_in，无参数、无真实考勤写入。实际调用才 print success、返回 success。每轮副作用去重；失败、禁用或取消不宣称成功，不自动重试工具。
知识库：在“知识与记录”输入标题与正文，点击“入库资料”；支持文本、分片和删除。真实业务资料当前为空。入库和检索使用现有付费 Pro/BAAI/bge-m3 和 Pro/BAAI/bge-reranker-v2-m3。空库不调用向量与重排，不编造业务资料。
关联记忆：本模式单独持久保存完整播报后的用户正文与回答，使用付费向量与重排；打断或过期轮次不写入，动作元数据不入库。这不是旧 Fay Bionic 记忆库或其反思机制，不与旧库自动共享。关闭记忆后不检索、不新增，但保留已有数据。验证资料在 acceptance-v2-20261110 隔离空间，真实默认空间知识和记忆均为0。运维能力调用日志为服务级。
手势：迎宾、告别、摊手讲解、点头，模型决定。每轮至多一个非待机动作，同动作从实际播放起冷却15秒。无公开手动动作或直接播报入口，旧API返回410。

验收：12项本地回归通过；真实浏览器支付模型检索、跨模型连接记忆召回通过；总开关和MCP独立开关阻止执行；否定/咨询/引用/旅游打卡不执行，明确请求及上下文确认执行。冻结语音实时输入成功调用实际MCP，打断后的新问题正常播报。MCP总数2→5，三次新增执行均有真实 success 日志。四动作完整帧数175/175/100/175，各仅触发一次并恢复待机。独立容器停止退出码0，重新启动后开关和数据不变；原正式六项服务健康。未重启服务器。
最终新模式默认全部开启，服务在线。真人麦克风、扬声器及动态观感仍需现场人工验收。本轮不新增五分钟性能结论。

服务器代码：/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2
持久数据：/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/runtime/qwen-realtime-v2
报告：/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/outputs/qwen-realtime-v2
启停：在服务器代码目录执行 bash control.sh start|stop|status|logs，仅管理 v2 容器。
版本回退：先停止v2，启动保留的 xiaolin-qwen-realtime-v1 容器；将 /opt/xiaolin/current/deployment/nginx.conf 的6444上游8771切回8770，nginx -t成功后reload。也可用备份 nginx-before-capabilities-v2.conf 核对该改动；若配置后来发生变化，勿直接覆盖整个配置。v2持久数据保留，6443不切换。
交付压缩包仅含源码、说明与脱敏测试证据，不含 API Key、配置凭据或真实记忆数据库。原始失败记录保留，最终修复结果见 -final 日志。
'''
(OUT / '使用与验收说明.txt').write_text(guide, encoding='utf-8-sig')
delivery = OUT / 'xiaolin-qwen-capabilities-v2.zip'
with zipfile.ZipFile(delivery, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in HERE.iterdir():
        if path.is_file() and path.suffix in {'.py', '.js', '.html', '.sh'}:
            archive.write(path, 'source/' + path.name)
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in {'.json', '.log', '.txt'}:
            archive.write(path, 'evidence/' + path.name)
digest = hashlib.sha256(delivery.read_bytes()).hexdigest()
(OUT / 'delivery.sha256').write_text(f'{digest}  {delivery.name}\n')
print(json.dumps({'status': 'PASSED', 'delivery': str(delivery), 'sha256': digest}, ensure_ascii=False))
