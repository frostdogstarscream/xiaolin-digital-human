# 本机 FunASR 与百炼 TTS

入口仍为 <http://127.0.0.1:8766/>。默认启动器会启动独立 CPU FunASR 服务，再启动 Fay 与 LiveTalking。原始素材、历史样片、本机 SAPI 适配器及知识库配置保持保留。

## 使用

1. 打开页面，自动连接数字人音视频并准备 Fay 核心，等待“音视频已连接”和“FunASR 语音识别：本机已就绪”。
2. 点击“开启语音唤醒”，在浏览器提示中允许麦克风访问。
3. 完整说出“小霖小霖”，停顿约一秒，数字人播报：“您好，我是小霖，很高兴为您服务，请问有什么可以帮您？”
4. 欢迎词播完后直接提问，说完自动识别并发给通义问答。也可以连说“小霖小霖，请介绍一下自己”，先播欢迎词，再回答后面的提问。每次回答完继续聆听，60 秒无交互后回到待唤醒。
5. 默认勾选“识别后自动发送问题”；取消勾选时只回填文字框。取消“连续聆听”可切回手动短录音，说完点击“结束录音并识别”，最长 30 秒；自动发送仍经过唤醒判断。
6. “停止语音唤醒”“取消录音”或“打断 / 停止”关闭麦克风；页面隐藏、断线或另一窗口接管也会释放设备。取消录音和关闭唤醒会回到待唤醒，重新连接展示也会重置唤醒状态。权限等待中可取消。

连续模式在用户开启后用本机音量检测切分短句，约 0.9 秒静音结束一段，每段最长 15 秒；纯静音不提交 ASR。唤醒由本机识别文本匹配完成，尚未唤醒的普通说话不会提交大模型。数字人播报期间暂停录音处理并丢弃回录片段，播完留 0.6 秒间隔再继续聆听，同时申请浏览器回声消除、降噪和自动增益。它属于“本机 ASR + 文本唤醒”，唤醒响应需要等短句识别完成；现场噪声、麦克风距离和扬声器回声仍需现场验证。

若应用内浏览器无法完成麦克风授权，请在正常 Edge 或 Chrome 中打开同一地址。浏览器权限属于当前浏览器，首次需允许。

## 实际链路

麦克风 MediaRecorder → 本机 8766 `/api/asr` → 本机 8780 FunASR/SenseVoiceSmall（CPU）→ `/api/voice-input` 唤醒判断 → 确定欢迎词/提问 → Fay → 百炼 Qwen Plus（仅问答）→ 百炼 `qwen3-tts-flash-realtime`（默认 Cherry 女声）→ PCM 音频块 → LiveTalking → WebRTC。音频合成过程中即可发送，WAV 文件在完成后保留给 Fay 缓存。

录音不上传云端 ASR，解码时的临时录音用后清理。识别后的问题文字会交给现有百炼模型；回答文字交给百炼 TTS。百炼合成 WAV 作为现有 Fay samples 语音文件保留。未添加知识库服务。

## 部署与配置

- 独立环境 `.venv-asr`：CPU PyTorch/torchaudio 2.9.1、FunASR 1.4.16，完整依赖见 `requirements-asr.lock.txt`。不改 LiveTalking 的 GPU torch 或 Fay 环境依赖。
- 模型：官方 `FunAudioLLM/SenseVoiceSmall`，固定 revision `3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`，保存在 `models/SenseVoiceSmall`，模型文件约 936 MB；下载清单记录 SHA256，LFS 权重对照官方摘要验证。
- 模型加载使用本地目录、关闭更新检查、不信任远程模型代码。Windows 中文路径的 SentencePiece 兼容通过本进程 tokenizer 子类读取序列化字节实现，未修改依赖包源码。
- ASR 服务只监听 `127.0.0.1:8780`，支持本机带标识头的 HTTP 录音识别和 Fay 原有 `send_url` WebSocket 协议。文件路径输入限定 Fay `samples` 和 `cache_data`。
- Fay `system.conf`：`ASR_mode=funasr`，`local_asr_ip=127.0.0.1`，`local_asr_port=8780`，`tts_module=bailian`。Fay 自身录音采集仍关闭，麦克风由当前控制台控制。
- Fay `config.json` 的 `source`：`wake_word=小霖小霖`、`wake_word_enabled=true`、`wake_word_type=common`、`wake_reply` 为上述欢迎词。浏览器桥接读取同一配置，语音唤醒不受页面“直接播报/通义问答”选项影响，唤醒后固定走问答；手动文字操作可直接使用。
- `source.wake_word_aliases` 记录有限的同音容错：“小林小林”“小琳小琳”“小林啊小林”“小霖啊小霖”。实际合成唤醒词的本机 ASR 输出为“小林啊小林。”，匹配后触发同一欢迎词。单说一次“小霖”不会唤醒。
- 百炼 TTS 复用既有密钥；`bailian_tts_realtime_enabled=true`、`bailian_tts_realtime_model=qwen3-tts-flash-realtime`、`bailian_tts_voice=Cherry`。原 `bailian_tts_model=qwen3-tts-flash` 保留作 HTTP 文件模式及其他输出入口。页面“配置播报音色”可更新受支持的系统音色 ID。Fay 合成缓存按模型和音色区分。
- 密钥和签名音频 URL 不回显，也不写入测试报告。TTS 请求启用正常 TLS 校验，下载音频时不转发 API Authorization。

`Start-DigitalHuman.cmd` 自动启动 ASR；ASR 也有独立 `Start-LocalASR.ps1`、`Stop-LocalASR.ps1`。`Stop-DigitalHuman.cmd` 沿用原行为，仅停止数字人桥接，独立 ASR/Fay 服务需分别停止。

## 已运行检查及验收边界

`tests/check_voice_integration.py` 已真实验证：2 秒百炼合成中文短句 → 本机识别“您好，欢迎来到展厅。” → Fay 真实百炼问答 → 百炼 TTS → LiveTalking WebRTC 接收端收到有声音频与视频。另验证 Fay 原生 ASR WebSocket、静音返回空结果、无效录音拒绝、非展示窗口拒绝、打断后队列清空。报告：`docs/voice-integration-validation-v1.json`。

本次模型预热后，2 秒样例的 CPU 识别耗时约 0.24–0.27 秒；一次完整问答从提交识别文本到服务端发出首段音频约 9.15 秒，包含大模型和云语音耗时，仅为本机单次测量。

自动测试输入是合成语音文件，不是人的现场录音。浏览器录音控件及本机服务状态已检查；实际麦克风权限、现场说话准确率、音色听感与扬声器回声仍待用户验证。Windows 浏览器自动操作在权限检查阶段因无法可靠确认当前页面 URL 而停止，未绕过安全检查。

唤醒更新真实验证：`tests/check_wake_flow.py` 使用百炼合成的“小霖小霖”音频，经本机 ASR 同音容错唤醒，完整欢迎词经 Fay/百炼 TTS/LiveTalking 播完后，再执行一次简短通义问答、实际收到有声音视频，最后关闭并确认休眠。另检查未唤醒提问不进入问答、单次名字不唤醒、标点、60 秒超时、同句问题保留以及非展示窗口拒绝。报告：`docs/wake-validation-v1.json`。`node tests/check_voice_listening.cjs` 验证静音丢弃、语音结束提交、等待播报完成、文字触发播报时暂停处理及设备释放。

恢复本机 TTS 可将 `tts_module` 改回 `windows_sapi` 后重启 Fay；非敏感原配置值保存在 `docs/speech-config-before-v1.json`，没有复制密钥。若切回旧版片段播放器，先停止数字人，再用 `Start-DigitalHuman.ps1 -Legacy`。

来源：[FunASR](https://github.com/modelscope/FunASR)、[SenseVoice](https://github.com/QwenAudio/SenseVoice)、[百炼 Qwen TTS](https://help.aliyun.com/zh/model-studio/qwen-tts-api)。

## 自动连接更新

数字人页面已移除手动连接按钮。每次打开或刷新会自动建立音视频连接；临时断线采用延迟重试。打开第二个窗口会自动接管，旧窗口暂停自动重试，避免两页抢占。旧窗口点击录音、播报或动作时也会自动切回。浏览器可能限制首次有声自动播放，点击录音、播报或人物即可启用声音；麦克风仍只在点击录音后请求权限。

回归入口：`node avatar-2d/tests/check_auto_connect.cjs`，覆盖首次自动连接、失败重试、多窗口停止争抢、操作自动接管与录音自动重连。

## 实时 TTS 更新

Fay 的每个播报文本片段使用百炼 WebSocket `commit` 模式，提交后持续接收 `response.audio.delta` 的 24 kHz PCM16。Fay 线程通过本机 `/api/tts/begin`、`packet`、`end` 将块交给桥接；桥接有状态重采样为 16 kHz，以 20 ms 帧送入原生 MelASR。只在片段首尾分别标记一次 start/end，避免分块造成动作反复触发或错误完成事件。每句话按 Fay 原有顺序合成和排队。

桥接启动时生成本机临时通道凭据，不使用浏览器传递云密钥。通道校验本机来源、临时凭据、任务、epoch、序号、音频大小和队列上限。打断清理队列并使旧任务失效，旧块返回 409；合成失败报告错误，不自动整句重播。完成后的文件继续进入 Fay 历史流程，桥接对已经直播过的那一次文件通知去重；新会话命中缓存仍能正常完整播放。

真实检查 `tests/check_realtime_tts.py` 已通过：4 段共 17.2 秒语音、55 个音频增量，首段 PCM 约 0.62 秒返回，从提交播报到服务端首次发送音频约 1.32 秒；第一句约 2.52 秒才合成完，已经在合成结束前开口。相同文本命中缓存后首音频约 0.52 秒，并验证无重复播放。生成中打断后队列为空、无后续说话帧、旧任务音频被拒绝。

一次真实通义问答的四段回答全部使用实时 TTS，从提交问题到首次音频约 12.44 秒。其中约 11.49 秒发生在首句进入实时 TTS 之前，TTS 开始到首次音频约 0.95 秒；该句首个 PCM 返回约 0.58 秒。该耗时包含 Fay/大模型生成首句的等待，不能把纯播报的 1.32 秒当成完整问答耗时，也不能与此前不同问题的 9.15 秒测试直接比较。报告：`docs/realtime-tts-validation-v1.json`。这些时刻来自服务端原生轨道发送与真实接收测试，现场扬声器播放时刻及主观听感需现场确认。

`tests/check_pcm_packets.py` 覆盖任意增量边界下重采样与整段结果一致、单次首尾标记、旧 generation 不入队；原页面自动连接和连续聆听行为检查仍通过。

回退 HTTP 文件模式：设置 `bailian_tts_realtime_enabled=false`，重启 Fay。回退 SAPI 则将 `tts_module=windows_sapi` 后重启 Fay。切换后刷新页面核对语音状态。

协议来源：[百炼 Qwen-TTS-Realtime WebSocket 接入指南](https://help.aliyun.com/zh/model-studio/interactive-process-of-qwen-tts-realtime-synthesis)。

## 当前关联记忆已关闭

业务知识库尚未接入，`config.json` 的 `memory.use_bionic_memory=false`。检索、后台对话/观察记忆写入、embedding 维度预检查与记忆调度现已遵守该开关，关闭时跳过相关工作；现有记忆文件保留。普通历史消息仍提供多轮上下文，不受该开关影响。

关闭后的同题单次真实检查：上下文准备约 0.093 秒，关联记忆检索已跳过（此前约 9.14 秒），模型首字约 0.566 秒，首句缓冲约 0.217 秒，进入 Fay 问答到首句送出约 0.876 秒；提交文字到服务端首段音频约 3.95 秒，包含入口及音频处理。这是一次测量，不含实际麦克风收音和 ASR。报告：`docs/fay-memory-disabled-timing-v1.json`，此前三次基线继续保留在 `docs/fay-stage-timing-v1.json`。
