"""Package only public client setup and sanitized actual cloud-terminal acceptance receipts."""
import hashlib,html,json,time,zipfile
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'avatar-2d/outputs/cloud-client-1660-wake-20261110'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text())
try:
    response=requests.get('https://36.133.88.94:6444/api/health',auth=(account['username'],account['password']),verify=str(ROOT/'runtime/server-4t4/delivery/xiaolin-root-ca.crt'),timeout=15)
    response.raise_for_status();live=response.json()
finally:account.clear()
(OUT/'live-server-health.json').write_text(json.dumps(dict(captured=time.time(),tls_verified=True,health=live),ensure_ascii=False,indent=2),encoding='utf-8')
acceptance=read('cloud-acceptance.json');state=read('final-state.json');cert=read('certificate-result.json');credential=read('credential-result.json')
checks=dict(actual_terminal_browser=acceptance['status']=='PASSED',tls=cert['tls_verified'] and acceptance['media']['secureContext'],
    no_local_inference=not state['local_backend_listeners'],encrypted_password=credential['status']=='SAVED' and not credential['plaintext_file'],
    cloud_online=live['status']=='ready',wake_word=live['wake_word']=='小霖小霖',business_switches_preserved=live['settings']['revision']==10,
    real_timeout=any(c['name']=='actual_timeout' and c['status']=='PASSED' and c['wait_seconds']>=59 for c in acceptance['cases']))
assert all(checks.values()),checks
report=dict(status='TECHNICAL_PASSED_PHYSICAL_AUDIO_PENDING',date='2026-11-10',architecture='GTX1660 terminal browser -> existing T4 server; no terminal inference',
    url='https://36.133.88.94:6444/',terminal='DESKTOP-7U752RG / 192.168.10.25',checks=checks,
    wake=dict(word='小霖小霖',standby_asr='Existing T4-local FunASR / SenseVoiceSmall CPU',active_model='qwen-audio-3.1-realtime-flash',
        inactivity_seconds=60,welcome='我在，请问有什么可以帮您？',model_and_tools_before_wake=False),
    credential_storage='Windows DPAPI CurrentUser, owner/SYSTEM ACL; no plaintext credential file',
    acceptance=acceptance,terminal_state=state,
    regression=dict(wake_unit_tests=6,resampler_input_rates=[16000,44100,48000],output_rate=16000,exact_output_samples_per_second=16000),
    limits=['Physical microphone/speaker and echo performance still need onsite human verification.',
            'Edge was verified on the terminal; Firefox compatibility is not marked passed.',
            'WebRTC reception was verified; this run did not separately force and record a TURN-only selected pair.',
            'The regular visible client may require first login; the desktop login-information shortcut provides the user-encrypted saved account.'],
    preservation=['Existing T4 switches, model credentials, material and old 6443 entry retained.',
                  'Terminal old local inference stopped gracefully; files retained and this run local backend tasks disabled.',
                  'No server/terminal reboot. Test service and client window remain available.'])
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
guide='''小霖新模式 — 一体机网页终端与服务器语音唤醒验收
日期：2026-11-10

架构：一体机只运行Edge网页、麦克风采集和音视频播放；ASR唤醒、Qwen实时模型、口型、动作、MCP和检索在36.133.88.94 T4服务器运行。
入口：https://36.133.88.94:6444/
一体机：DESKTOP-7U752RG，192.168.10.25，Admin。

使用：
1. 在一体机桌面双击“启动小霖新模式”。
2. 如出现首次登录框，打开桌面“小霖网页登录信息”，复制账号和密码。密码按当前Windows用户DPAPI加密保存，未写明文密码文件。
3. 点击网页“开启唤醒监听”，允许麦克风权限。
4. 说“小霖小霖”：播放“我在，请问有什么可以帮您？”；说“小霖小霖，我要打卡”则直接进入本轮问答/工具流程，不额外重复欢迎。
5. 唤醒后可连续说话，不必每句重复唤醒词。连续60秒无交互返回待唤醒；也可点“返回待唤醒”。
6. “停止对话”关闭监听；“停止小霖新模式”关闭一体机专用浏览器窗口，服务器仍在线。人物全屏按钮继续可用。

验收通过：
一体机实际Edge访问服务器HTTPS/WSS并解码1080×1920画面；严格验证证书，没有关闭TLS校验。
未唤醒的“我要打卡”没有连接大模型、没有调用工具。
“唤醒词＋问题”识别后实际调用MCP并完成语音播放；单独唤醒词完成欢迎播报；唤醒后不重复说唤醒词的追问也正常调用MCP。
实际等待约60.3秒后自动回到待唤醒，随后无唤醒词的请求再次被挡住，大模型连接保持关闭。
固定音频只用于验收。真实麦克风、扬声器、回声和现场动态观感仍需人工体验，不将固定音频等同于真人麦克风验收。
六项唤醒单元检查通过；16k/44.1k/48k浏览器输入统一生成16k PCM的采样数检查通过。

客户端路径：%LOCALAPPDATA%\\XiaolinCloudClient
控制：Control-CloudClient.ps1 -Action Start|Stop|Status|Login
凭据：web-access.clixml（DPAPI CurrentUser加密，只允许当前用户和SYSTEM；不要当作明文配置迁移）
信任：当前用户专用小霖CA，SHA1 D160BEE768369CAD3A568F0514F529E1C66E0CFF。
服务端代码：/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2
本次只给6444新模式增加唤醒，不改6443旧模式。
原本机部署文件保留停用，不属于当前网页客户端。误按原“启动小霖”可能重新运行旧本机版，请使用带“新模式”的入口。

首次欢迎接口试验的失败记录已保留；最终改用已验证的session.update和文本事件协议，并完整复测通过。
交付包仅包含源码和脱敏验收记录，不含网页账号密码、API Key、DPAPI凭据文件、SSH私钥或记忆数据库。
'''
(OUT/'使用与验收说明.txt').write_text(guide,encoding='utf-8-sig')
page='<!doctype html><meta charset="utf-8"><title>小霖网页终端与唤醒验收</title><style>body{font:16px/1.8 system-ui;max-width:960px;margin:40px auto;padding:20px;color:#213b43}pre{white-space:pre-wrap;background:#eef5f5;padding:24px;border-radius:12px}img{width:100%;border-radius:12px}</style><h1>小霖 · 一体机网页终端与语音唤醒</h1><pre>'+html.escape(guide)+'</pre><img src="cloud-fullscreen.jpg" alt="一体机接收T4数字人全屏画面">'
(OUT/'验收报告.html').write_text(page,encoding='utf-8')
sources={}
for base,names in [(ROOT/'avatar-2d/experiments/qwen-realtime-v2',['gateway.py','wake_gate.py','provider.py','demo.js','index.html','test_wake_gate.py']),
                   (Path(__file__).parent,['Control-CloudClient.ps1','Install-CloudClient.ps1','Install-ClientCertificate.ps1','Save-ClientLogin.ps1','check_cloud_browser.py','Start-CloudBrowserAcceptance.ps1','final_cloud_client_snapshot.ps1'])]:
    for name in names:
        path=base/name;sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
(OUT/'source-sha256.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
bundle=OUT/'xiaolin-cloud-client-and-wake-20261110.zip'
with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in ('.json','.txt','.html','.jpg'):archive.write(path,'evidence/'+path.name)
    for name in sources:archive.write(ROOT/name,'source/'+name)
(OUT/'delivery.sha256').write_text(hashlib.sha256(bundle.read_bytes()).hexdigest()+'  '+bundle.name+'\n')
print(json.dumps(dict(status=report['status'],checks=checks,bundle=str(bundle)),ensure_ascii=False))
