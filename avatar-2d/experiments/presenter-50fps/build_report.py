"""Build auditable delivery; never bundle browser profiles or credentials."""
import json,hashlib,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;OUT=HERE.parents[1]/'outputs/presenter-50fps'
read=lambda name:json.loads((OUT/name).read_text(encoding='utf-8'))
base=read('baseline25-report.json');optimized=read('optimized50-report.json');manifest=read('manifest-final.json')
browser=read('browser-startup-warmed/report.json');initial=read('browser/report.json');warm=read('browser-warmed-actions/report.json')
reconnect=read('browser-reconnect/report.json')
failures=[]
for name in ['initial-fp32-progress.json','initial-fp16-progress.json']:
    snapshot=read(name);x=snapshot['latest']
    failures.append(dict(source=name,status='STOPPED_EARLY_BELOW_TARGET',seconds=x['seconds'],receive_fps=x['received']/x['seconds'],queue_seconds=x['total_seconds']))
summary=dict(status='EXPERIMENT_PASSED_HUMAN_VISUAL_REVIEW_PENDING',production_switched=False,
    preview_url='https://36.133.88.94:6444/experiments/50fps/',live_url='https://36.133.88.94:6444/experiments/50fps/live',
    resolution=[1080,1920],fps=50,precision='FP16',idle_segments=manifest['idle']['segments'],
    original_idle_seconds=30,offline_interpolation='bidirectional DIS optical flow; not native 50fps capture',
    no_consecutive_repeat=all(a!=b for a,b in zip(optimized['idle_segment_history'],optimized['idle_segment_history'][1:])),
    baseline25={k:base[k] for k in ['render_fps','receive_fps','latency_summary']},
    optimized50={k:optimized[k] for k in ['duration_seconds','render_fps','receive_fps','latency_summary','queue_last_minute','input_end_to_drain_seconds','checks','gpu_peak_allocated_bytes','gpu_peak_reserved_bytes','process_peak_rss_bytes']},
    browser=dict(initial_fps=initial['receive_fps'],warmed_fps=warm['receive_fps'],startup_warmed_fps=browser['receive_fps'],dropped_frames=browser['dropped_frames'],strict_tls=browser['strict_tls'],fresh_reconnect=reconnect.get('fresh_media_after_reconnect',False),device='developer PC Edge, not physical all-in-one'),
    retained_failed_trials=failures,cloud_llm_tts_calls=0,physical_microphone_speaker=False,human_visual_accepted=False)
(OUT/'evaluation-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
fmt=lambda x:f'{x:.2f}'
text=f'''# 小霖 50 帧与三段随机待机实验验收

日期：2026-11-10。结论：独立实验数值验收通过，人工动态观感待确认。正式 6444 根入口、原 Fay 6443、模型凭据、记忆和唤醒逻辑未切换。

预览：[25/50 帧对照与四动作视频]({summary['preview_url']})；[独立实时实验]({summary['live_url']})。沿用现有网页登录账号和密码。实验不采集麦克风、不调用 LLM/TTS/MCP，只使用冻结语音。独立实验中的动作按钮仅用于验收。

## 待机方式

原始 30 秒素材保留，光流补到 1500 帧，1080×1920 / 50 fps。三个完整连续片段：A 为 0–10.8 秒，B 为 10.8–22 秒，C 为 22–30 秒，即 10.8 / 11.2 / 8 秒。切点避开目视确认的约 9 秒和 18 秒眨眼。

片段结束后按末帧与候选入口姿态差异进行加权随机，不连续重复同一段。普通问答不重置待机进度；动作结束后选择姿态接近的片段，不固定回到整条视频第 0 帧。第一段仍可能自然被选中；不是禁止使用它。未加入跨片段混合或人脸形变过渡，所有六种接缝均保留供人工检查。

## 性能

两组在同一张 T4 顺序测试、使用同一冻结音频。25 帧参考为 FP32；50 帧配置同时使用 FP16、CPU 线程限制和融合遮罩缓存，因此这是整套配置对照，不是只改变帧率的单变量实验。

| 项目 | 25 fps 对照 | 50 fps 实验 |
|---|---:|---:|
| 连续输入时长 | {base['duration_seconds']:.1f} 秒 | {optimized['duration_seconds']:.1f} 秒 |
| 渲染 | {base['render_fps']:.3f} fps | {optimized['render_fps']:.3f} fps |
| 服务器内 WebRTC 接收 | {base['receive_fps']:.3f} fps | {optimized['receive_fps']:.3f} fps |
| 首个口型帧中位数 | {base['latency_summary']['first_generated_mouth_ms']['median']:.1f} ms | {optimized['latency_summary']['first_generated_mouth_ms']['median']:.1f} ms |
| 首播回调中位数 | {base['latency_summary']['first_play_callback_ms']['median']:.1f} ms | {optimized['latency_summary']['first_play_callback_ms']['median']:.1f} ms |
| 首播回调 P95 | {base['latency_summary']['first_play_callback_ms']['p95']:.1f} ms | {optimized['latency_summary']['first_play_callback_ms']['p95']:.1f} ms |

首播数据是冻结 PCM 入队至渲染音频发送回调，不含用户说话、ASR、LLM 或云 TTS；每组五次，P95 样本较小。50 帧首播 P95 比对照增加 {optimized['latency_summary']['first_play_callback_ms']['p95']-base['latency_summary']['first_play_callback_ms']['p95']:.1f} ms。

50 帧末分钟音频队列最大 {optimized['queue_last_minute']['max_seconds']:.2f} 秒，趋势 {optimized['queue_last_minute']['slope_seconds_per_minute']:.3f} 秒/分钟；输入停止后 {optimized['input_end_to_drain_seconds']:.3f} 秒排空。四动作 350 / 350 / 350 / 200 帧完整执行；旧代次拒绝、打断、重连通过。

模型使用 FP16，CPU 小矩阵线程受限，融合遮罩缓存；原素材分辨率和动作时长未降低。PyTorch 峰值已分配显存约 {optimized['gpu_peak_allocated_bytes']/2**30:.2f} GiB，包含调优峰值；进程峰值 RSS 约 {optimized['process_peak_rss_bytes']/2**30:.2f} GiB，包含帧缓存。浏览器客户端不承担这些模型和缓存。

## 公网浏览器

开发电脑 Edge、严格验证专用 CA。初次未预热四动作接收 {initial['receive_fps']:.2f} fps，未达标记录保留；预热后复测 {warm['receive_fps']:.2f} fps。将内存页和口型/音频特征预热移至实验服务启动阶段后，首次浏览器四动作测试 {browser['receive_fps']:.2f} fps，丢帧 {browser['dropped_frames']}，1080×1920。另行验证重连后接收新视频帧。

公网正式验收仅是当前网络、开发机 Edge 的短时测试。服务端五分钟验收与浏览器约 {browser['seconds']:.1f} 秒验收是不同范围；未声称完成公网五分钟或一体机真人麦克风/扬声器验收。未强制 TURN，不能据此承诺所有中继网络均为 50 fps。

## 保留的失败与限制

FP32/batch4 和未限制 CPU 线程的 FP16 初次尝试均因帧率不足与音频积压停止，原始进度与报告保留。旧眼睛闭合切点图也保留，最终图为 all-six-transitions-reviewed.jpg。光流补帧、FP16 口型和随机接缝仍需人工观看视频确认；不等于原生拍摄的 50 fps。

## 运维

独立容器：`xiaolin-50fps-preview`；内部端口 `127.0.0.1:8788`，经现有 HTTPS 6444 的 `/experiments/50fps/` 子路径访问并继承访问认证。实验 ICE 为 UDP 10200–10249，在已授权公网端口段内。实验未挂载大模型/TTS/embedding 凭据，只挂载现有 TURN 密钥供 WebRTC 使用。

启动：`sh /opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/presenter-50fps/start-preview.sh`

停止：`docker stop -t 20 xiaolin-50fps-preview`。不会停止正式服务。未设置实验自动开机启动，未重启服务器。

源码：`avatar-2d/experiments/presenter-50fps/`。新增素材在独立 `runtime/presenter-50fps/`；原素材未覆盖。两项调度单元测试通过；Python 编译检查通过。交付包不含浏览器配置目录、网页登录凭据、API Key 或模型权重。
'''
(OUT/'验收报告.md').write_text(text,encoding='utf-8')
files=[p for p in HERE.iterdir() if p.suffix in ('.py','.html','.sh','.md')]
files += [p for p in OUT.iterdir() if p.suffix in ('.json','.md','.jpg','.mp4') and p.name!='SHA256.json']
files += [OUT/n/'report.json' for n in ['browser','browser-diagnostic','browser-warmed-actions','browser-startup-warmed','browser-reconnect']]
files += [OUT/'browser-startup-warmed/live-50fps.jpg']
checks={str(p.relative_to(HERE.parents[2])):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
(OUT/'SHA256.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
with zipfile.ZipFile(OUT/'xiaolin-50fps-random-idle-evaluation.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in files+[OUT/'SHA256.json']:
        if p.exists():z.write(p,str(p.relative_to(HERE.parents[2])))
print('Report and safe delivery archive written')
