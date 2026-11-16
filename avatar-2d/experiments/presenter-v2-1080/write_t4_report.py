"""Summarize downloaded evidence; never substitutes local results for T4 measurements."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/presenter-v2-1080'
EVIDENCE=OUT/'t4-evidence'
RUN=EVIDENCE/'avatar-2d/outputs/presenter-v2-1080/t4-run02'
report=json.loads((RUN/'report.json').read_text())
resources=json.loads((RUN/'resources.json').read_text())
reconstruction=json.loads((EVIDENCE/'avatar-2d/outputs/presenter-v2-1080/t4-reconstruction.json').read_text())
gpu=[]
for row in resources:
    for line in row.get('nvidia_smi','').splitlines():
        fields=[f.strip() for f in line.split(',')]
        if len(fields)==4 and fields[0]==report.get('gpu_uuid'):
            gpu.append(dict(memory_mib=float(fields[1]),utilization_percent=float(fields[2]),temperature_c=float(fields[3])))
summary=dict(status=report['status'],scope=report['scope'],duration_seconds=report.get('duration_seconds'),
    render_fps=report.get('render_fps'),receive_fps=report.get('receive_fps'),checks=report.get('checks'),
    sampled_gpu_peak_memory_mib=max((r['memory_mib'] for r in gpu),default=None),
    sampled_gpu_peak_utilization_percent=max((r['utilization_percent'] for r in gpu),default=None),
    sampled_gpu_peak_temperature_c=max((r['temperature_c'] for r in gpu),default=None),
    exact_reconstructed_frames=sum(row['pixel_exact_frames'] for row in reconstruction['clips']),
    reconstructed_frames=sum(row['frames'] for row in reconstruction['clips']))
(OUT/'t4-performance-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
lines=['小霖新形象 1080p · T4持续性能验收','日期：2026-11-10',
    '结论：'+report['status'],
    '范围：服务器内部、原生WebRTC双端回环；不是外网浏览器或真人麦克风验收。',
    '正式服务未切换、未重启；GPU0维持正式部署，GPU1隔离测试。',
    '测试目录：/opt/xiaolin/evaluations/presenter-v2-1080',
    '输出：1080×1920、25fps；Wav2Lip256、FP32、batch4、H.264 NVENC。',
    '固定16kHz PCM连续按实时速度输入；无LLM/TTS/ASR云调用。',
    f"源视频恢复帧数：{summary['exact_reconstructed_frames']}/{summary['reconstructed_frames']}与本机逐帧像素摘要一致。",'']
if 'duration_seconds' in report:
    lines += [f"持续输入：{report['duration_seconds']:.3f}秒",
        f"渲染：{report['render_fps']:.4f}fps；服务器内接收：{report['receive_fps']:.4f}fps",
        f"末分钟队列最大：{report['queue_last_minute']['max_seconds']:.3f}秒；中位数：{report['queue_last_minute']['median_seconds']:.3f}秒",
        f"末分钟队列斜率：{report['queue_last_minute']['slope_seconds_per_minute']:.5f}秒/分钟",
        f"输入结束后排空：{report['input_end_to_drain_seconds']:.3f}秒",
        f"模型加载及预热：{report['model_load_and_warmup_seconds']:.3f}秒（不含此前模块导入）",
        f"进程峰值RSS：{report.get('process_peak_rss_bytes',0)/1024**3:.3f}GiB（包含帧缓存文件的内存映射，不等于私有堆占用）",
        f"系统峰值已用内存：{report.get('host_peak_used_bytes',0)/1024**3:.3f}GiB（包含其他服务）",
        f"采样显存峰值：{summary['sampled_gpu_peak_memory_mib']}MiB；峰值温度：{summary['sampled_gpu_peak_temperature_c']}℃",
        f"PyTorch峰值已分配：{report.get('gpu_peak_allocated_bytes',0)/1024**2:.2f}MiB",
        f"待机循环：{report.get('idle_loops')}次（包含预热/短音频阶段）",'']
    lines += ['分分钟检查：']
    for row in report['cases']:
        lines.append(f"第{row['minute']}分钟：渲染{row['render_fps']:.3f}fps，接收{row['receive_fps']:.3f}fps，最大队列{row['max_queue_seconds']:.3f}秒")
    lines += ['','四动作：']
    for row in report.get('actions',[]):lines.append(f"{row['action']}：{row['actual']}/{row['expected']}帧")
if 'latency_summary' in report:
    lines += ['','5次预热后短音频延迟：']
    for key,label in [('first_generated_mouth_ms','PCM到首个生成口型帧'),('first_play_callback_ms','PCM到服务端首播回调')]:
        value=report['latency_summary'][key]
        lines.append(f"{label}：中位数{value['median']:.1f}ms，P95 {value['p95']:.1f}ms")
    lines += ['这些是本次5次样本的统计值，不包含识别、大模型、云TTS或外网传输等待。',
        '服务端播放回调不等于客户端扬声器实际出声时间。']
lines += ['','验收项：']
for key,value in report.get('checks',{}).items():lines.append(f"{key}：{'通过' if value else '未通过'}")
if report.get('error'):lines.append('错误：'+report['error'])
connections=report.get('reconnect',{}).get('connections',[])
if connections:
    lines += ['','连接计时：',
        f"首次WebRTC就绪检查：{connections[0]['seconds']:.3f}秒；热重连：{connections[-1]['seconds']:.3f}秒。",
        '该检查等到收到30帧才完成，包含初始化与采样窗口，不能当作首帧延迟。']
lines += ['','复测说明：',
    '首轮持续300秒的帧率、队列、排空、动作、打断与重连指标达标，但测试脚本将主动停止媒体轨道的MediaStreamError误判成接收异常。',
    '首轮原始ACCEPTANCE_NOT_MET记录保留；修正为显式记录预期关闭和意外关闭后，第二轮重新完整运行300秒。',
    '未修改渲染实现、精度、画面尺寸、音频输入或验收阈值。',
    f"本轮关闭事件记录：{json.dumps(report.get('receiver_events',[]),ensure_ascii=False)}"]
lines += ['','交付与边界：','原始report.json、samples.jsonl、resources.json、模型/脚本摘要和容器日志均保留。',
    '本轮不切换正式默认形象；公网浏览器1080p接收、TURN、真人麦克风和扬声器仍需单独验收。',
    '人物/嘴部动态观感需人工确认；整幅1080p不改变Wav2Lip256内部口型分辨率。']
(OUT/'T4持续性能验收.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
