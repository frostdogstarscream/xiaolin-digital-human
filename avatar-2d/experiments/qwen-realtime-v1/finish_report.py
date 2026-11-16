"""Consolidate real API/browser evidence without including private browser configs."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/qwen-realtime-v1'
def browser(name):
    raw=(OUT/(name+'.log')).read_text(encoding='utf-8-sig')
    result=json.loads(raw.split('### Result',1)[1].split('### Ran',1)[0].strip())
    (OUT/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
trial=browser('browser-trial');mic=browser('browser-microphone');barge=browser('browser-barge-in-final')
reconnect=browser('browser-connect-final')
local=json.loads((OUT/'probe/report.json').read_text(encoding='utf-8'))
cloud=json.loads((OUT/'t4-probe-report.json').read_text(encoding='utf-8'))
access=json.loads((OUT/'access-report.json').read_text(encoding='utf-8'))
assert all(row['status']=='PASSED' for row in (trial,mic,barge,local,cloud,access,reconnect))
report=dict(status='PASSED',scope='isolated real-time audio trial, not complete management backend or business acceptance',
    url='https://36.133.88.94:6444/',model='qwen-audio-3.1-realtime-flash',voice='longanqian_v3.1',
    profile='presenter-v2-1080',local_probe=local,server_probe=cloud,public_browser=trial,
    fake_microphone=mic,speech_barge_in=barge,access=access,public_reconnect=reconnect,
    lifecycle=dict(graceful_stop_exit_code=0,oom_killed=False,restarted=True),
    pending=['physical microphone and loudspeaker acceptance','MCP integration','long-term memory integration','automatic gesture planning in this mode','full management backend'],
    boundary_note='An earlier barge-in trial produced an unsupported success claim in exhibition context. Raw transcript retained; system instruction strengthened and final trial correctly stated tool is unavailable. This is not a guarantee of general business-action correctness.')
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
qa=trial['cases'][0];recovery=trial['cases'][-1]
text=f'''小霖 · Qwen实时语音新模式试用记录
日期：2026-11-10
入口：https://36.133.88.94:6444/
认证：沿用原正式模式访问账号；API Key仅在服务端从原百炼配置读取。
原正式模式：https://36.133.88.94:6443/ 保持运行。

模型：qwen-audio-3.1-realtime-flash
工作空间：用户指定北京专属域名
音色：longanqian_v3.1（按3.1官方音色配置，服务端已接受）
人物：本轮1080×1920新形象，30秒自然待机，Wav2Lip256，GPU1，NVENC。

已实际通过：
- 本机与T4实际模型连接、文字/音频流输出。
- 公网Chrome真实1080×1920音视频接收。
- 问题文本 -> 实时模型 -> 流式PCM -> 16kHz重采样 -> Wav2Lip -> WebRTC播放。
- 冻结语音2.32秒经WebSocket实时输入，返回识别字幕、文字与声音。
- Chrome虚拟麦克风实际getUserMedia/AudioWorklet采集，16kHz，上传{mic['micBytes']}字节，成功识别并回答。
- 用户按钮打断、队列清空、打断后新问题恢复。
- 插话语音触发自动打断，旧回复未继续完成播放，新回复正常完成。
- 独立服务正常停止，退出码0；随后启动恢复，正式六个服务仍健康。
- HTTPS证书校验开启；未登录401、错误Origin 403；say/action入口410。

观察到的延迟（少量试用值，不是长期性能基准）：
本机固定短句：首PCM {local['first_audio_seconds']:.3f}秒。
T4固定短句：首PCM {cloud['first_audio_seconds']:.3f}秒，连接及配置{cloud['connect_configure_seconds']:.3f}秒。
公网文字问答：服务端输入到首PCM {qa['inputToPcmMs']:.1f}ms；首PCM到播放回调{qa['pcmToPlayMs']:.1f}ms。
浏览器点击发送到观察到服务端首播回调：{qa['firstPlayWallMs']}ms；打断后问答{recovery['firstPlayWallMs']}ms。
服务端播放回调不等于真人扬声器实际出声时间。

使用：
页面自动连接人物音视频；点击“开启实时对话”后，允许浏览器麦克风权限并直接说话。
此试用页无需唤醒词，也可输入文字问题。停止对话会关闭模型语音连接；人物仍可待机。

本轮边界：
这里交付的是独立实时语音试用模式，不是完整的新管理后台。
MCP、长期记忆、知识库和自动手势尚未接入此模式；四段素材保留在独立人物缓存中。
本模式会话不写入原Fay历史与记忆；既有凭据、原正式模式和业务配置保持现状。
真人麦克风、回声环境、扬声器观感与口型动态效果仍需现场人工确认。
首次插话试验在展馆上下文出现“打卡成功”的无工具自然语言回复，原记录已保留；强化能力边界提示后复测明确说明本模式不能办理。
本轮仅验收语音链路，不将模型自然语言回复当作业务执行凭证。

部署与启停：
目录：/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v1
容器：xiaolin-qwen-realtime-v1
控制：bash 上述目录/control.sh start|stop|status|logs
内部服务127.0.0.1:8770；HTTPS反代6444；独立ICE端口10100–10149，使用已有TURN服务。
Nginx原配置备份：/opt/xiaolin/evaluations/presenter-v2-1080/nginx-before-realtime-v1.conf
没有执行服务器重启。
'''
(OUT/'实时语音新模式试用记录.txt').write_text(text,encoding='utf-8')
archive=OUT/'qwen-realtime-v1-delivery.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as package:
    for path in Path(__file__).parent.iterdir():
        if path.suffix in ('.py','.html','.js','.sh'):package.write(path,'code/'+path.name)
    for path in OUT.iterdir():
        if path.suffix in ('.json','.log','.txt'):package.write(path,'evidence/'+path.name)
    package.write(OUT/'probe/response-24k.wav','evidence/response-24k.wav')
digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
(OUT/'delivery-sha256.txt').write_text(digest+'  '+archive.name+'\n')
print(json.dumps(dict(status='PASSED',url=report['url'],sha256=digest),ensure_ascii=False))
