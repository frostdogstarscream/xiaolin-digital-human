# LiveTalking 实时数字讲解员

## Firefox 自动连接兼容修复

如果 Firefox 在麦克风授权前仅提供 `.local` mDNS 候选，而 Windows 无法解析这些名称，当前 aioice 会在收到 `end-of-candidates` 时提前裁掉 ICE 组件，随后服务端答案变成零候选，页面持续重连。

本机集成入口通过 `service/rtc_compat.py` 对仅含 mDNS 候选的 offer 保持 half-trickle ICE 开放，让服务端先公布可用候选，再通过浏览器发起、带原有凭据认证的 ICE 检查学习 peer-reflexive 地址。正常 IP 候选不改动，不修改浏览器隐私、系统防火墙或外部 STUN/TURN 配置，vendor 源码保持原样。

`tests/check_mdns_compat.py` 用真实 aiortc 复现修复前答案零候选，验证修复后能够完成 ICE 并收到音频和视频。记录见 `docs/mdns-compat-validation-v1.json`。当前用户 Firefox 会话的实际稳定连接与持续输出记录见 `docs/firefox-live-validation-v1.json`。

默认启动入口：双击 `avatar-2d/Start-DigitalHuman.cmd`，访问 <http://127.0.0.1:8766/>。

## 当前链路

文字输入/本机 FunASR → Fay → 百炼通义千问（问答模式）→ 百炼 `qwen3-tts-flash-realtime` WebSocket 音频块 → 有状态 24 kHz 转 16 kHz 单声道 PCM → LiveTalking MelASR → Wav2Lip256 → LiveTalking HumanPlayer / RTCManager → 浏览器 WebRTC 音视频。实时音频通道及测试见 [语音接入说明](VOICE.md)。

直接播报模式跳过大模型。人物画面在本机生成；百炼问答和语音合成依赖联网。浏览器点击“开启语音唤醒”后申请麦克风权限，录音交给本机 ASR。首次播放可能需要点击人物或播报按钮以启用声音。

本次使用已下载的官方 LiveTalking 固定版本 `c7269433a2b6ecebcd9342445d2ecc882c98b0da`。`vendor` 内源码不改动；本地扩展 `service/live_engine.py` 继承其 `LipReal`，使用原生 MelASR、WebRTCOutput、HumanPlayer 和 RTCManager，增加 Fay PCM 输入、动作调度、匹配动作的人脸推理以及打断时的队列清理。`service/live_app.py` 复用原控制台的 Fay 与百炼配置接口。这是集成现有 Fay 的 LiveTalking 实时运行入口，并非直接启动原仓库的通用 `app.py`。

## 使用

1. 打开页面后自动连接，等待音视频就绪。当前只允许一个展示会话；另一个窗口接管时旧画面会断开，防止重复声音。
2. 选择“直接播报”或“通义问答”，输入文字并发送。
3. “下一次播报动作”可选自动、仅说话、迎宾挥手、告别挥手、摊手讲解、点头确认。自动模式沿用 Fay 动作语义，同一回答的动作只在第一段语音开始时触发。
4. 动作按钮立即播放对应动作，可以在说话过程中点击，不中断语音。动作顺序播放一次，结束保持它自己的中性末帧；长语音继续驱动这张中性姿态的嘴型。
5. “打断 / 停止”停止当前 Fay 请求和待播语音，清理音频特征、音视频发送队列，回到迎宾素材中性首帧。全屏可按 Esc 退出并打断。

沿用之前修正人物比例的方法：待机取迎宾素材的中性姿态，不恢复偏宽的原始待机底板，不逐帧缩放或改变脸型。点头仍使用已有时间剪辑候选；其自然度需要用户验收。

## 本机接口

所有 HTTP 仅监听 `127.0.0.1:8766`，不设外部 STUN/TURN。写操作要求 `X-Avatar-Client: 1`，浏览器 Origin 限定本机控制台。WebRTC offer 和展示控制另传 WebSocket `state` 返回的 `client_id`，请求头为 `X-Avatar-Viewer`。

| 接口 | 行为 |
|---|---|
| `GET /ws` | 控制台状态、文字回答、语音开始/结束及展示归属事件 |
| `POST /api/offer` | 原生 LiveTalking WebRTC 协商，JSON `sdp`、`type`，返回 `sdp`、`type`、`sessionid`；接管旧会话 |
| `POST /api/say` | Fay 直接播报，JSON `text` |
| `POST /api/chat` | Fay → 已配置百炼的真实问答，JSON `text` |
| `POST /api/action` | JSON `action`；`play: true` 立即播放，省略时选择下一轮语音动作 |
| `POST /api/interrupt` | 打断当前请求、语音和动作 |
| `GET /api/health` | Fay、模型、WebRTC 状态、语音任务时间戳、累计渲染计数；不返回密钥 |

语音状态的 `started_at`/`ended_at` 来自原生音频发送轨道回调，代表服务端发送进度，不代表耳机或扬声器的物理播放时刻。开发机自动采用 FP16；计算能力低于 8.0 的 CUDA 设备采用 FP32，不能据此保证 GTX 1660 的帧率。

## 检查及回退

真实接收测试：`avatar-2d/.venv/Scripts/python.exe avatar-2d/tests/check_live_stream.py`。测试建立真实 aiortc 接收端，依次检查四动作＋非静音语音、说话时切动作、打断后无新增说话帧、一次百炼短问答、会话重连、请求来源限制。报告保存在 `docs/livetalking-validation-v1.json`。

测试会接管当前展示窗口，并发起一次已配置百炼的短问答。测试结束后，刷新原窗口即可自动重新接管。此脚本用于本机接入验收，不是目标展示机、麦克风、扬声器、逐音素口型和长时间稳定性验收。

旧版片段生成与播放逻辑、页面、素材、历史样片和 Fay 服务保留。回退：先运行 `Stop-DigitalHuman.cmd`，再运行 `powershell -NoProfile -ExecutionPolicy Bypass -File avatar-2d/Start-DigitalHuman.ps1 -Legacy`；恢复实时版则停止后正常启动。

不在本轮修改麦克风 ASR、知识库或业务工具。现有模型权重的商业授权核实状态沿用原记录。
