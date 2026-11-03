# 真人 2D 数字人工作目录

## 当前语音：本机 FunASR + 百炼 TTS

默认入口采用本机 SenseVoiceSmall 识别，支持“小霖小霖”唤醒和连续问答。语音合成使用百炼 `qwen3-tts-flash-realtime`，默认 Cherry 女声；PCM 音频块直接进入 LiveTalking，合成过程中即可播报，完成后保存 WAV 用于 Fay 缓存。已测试实际分块生成与接收、缓存重播、打断和通义问答。独立 ASR 环境不占数字人 GPU；麦克风需浏览器授权，现场回声和识别效果需说话验证，详见 [语音接入说明](docs/VOICE.md)。以下历史章节的 Windows SAPI 指此前版本。

## 当前默认入口：Fay + LiveTalking WebRTC 实时版

`Start-DigitalHuman.cmd` 现在默认启动本机 LiveTalking 实时流，仍使用 <http://127.0.0.1:8766/>。保留 Fay 与百炼配置，支持四动作、边说话边切动作、语音打断与会话接管。具体链路、操作、测试和旧版回退见 [LiveTalking 实时说明](docs/LIVETALKING.md)。以下章节是此前阶段记录，其中“短片段生成后播放”指旧版；原文件和样片保留。

## Fay 接入：本机控制台、语音与四动作已联调

双击 `Start-DigitalHuman.cmd`，访问 `http://127.0.0.1:8766/`。支持通过 Fay 直接播报、百炼通义问答、四动作预览、打断、全屏展示和本机模型配置。使用说明、接口映射、实际测试与限制见 [Fay 2D 接入说明](docs/FAY-2D.md)。停止入口为 `Stop-DigitalHuman.cmd`。

当前使用百炼 Qwen Plus 生成回答、Windows 本机中文语音合成、常驻 Wav2Lip256 生成口型。采用短片段生成后播放；麦克风 ASR、知识库与外部业务工具尚未验收。此前视频素材和离线测试记录保留如下。

## 当前预览：v3 修正开头待机与迎宾的体型差异

用户指出 32 秒预览开头约 2 秒人物偏大。对 v2 开头帧对比后确认：头顶和脚底高度基本对齐，但原待机底板的肩臂前景轮廓比迎宾片段宽，切换时有体型变化感。仅统一头脚高度不足以消除这类由生成素材带来的轮廓差异。

v3 的开头一秒改用迎宾动作首帧的休止姿态，紧接迎宾动作。后续各动作结束的一秒停留使用该动作自身的末帧，减少回到另一条待机素材导致的形体跳变。这些停留是用于离线审阅的一秒静止帧，并非已制作新的长期循环待机视频。动作片段时长保持一致。

新版文件：`outputs/motion-review-v3/motion-sequence.mp4`。仍为 32 秒、800 帧、720×1280、25 fps、无音轨，完整严格解码和独立帧计数通过。开头停留到迎宾连接处的全帧平均像素差由约 1.601 降至 0.0018；这仅衡量该连接处同姿态帧的连续性，不代表全片人工视觉验收。已查看开头 0、0.48、1、2 秒的前后对照图，保存在同目录 `opening-before-after.jpg`。

`Open-Motion-Review.cmd`、人物清单和验证汇总已指向 v3；旧预览保留。复现脚本为 `tools/rebuild_motion_review.py`，输出目录已存在时会停止，避免覆盖。此次修改只调整离线预览中的停留画面来源；各动作口型推理结果和实时联调状态以原有测试记录为准。

## 前一阶段：新增 1760 原片，轻点头剪辑候选已完成口型测试

新原片 `1760` 已保存在 `assets/presenter-v1/motions-v1/incoming-1760/source.mp4`，5.016667 秒、720×1280、121 帧，严格音视频解码通过，SHA256 为 `7cdee2753d43efa820d11eac385898167c13994116435942fc887df8eb287bd5`。

抽样查看原片与 0.8–1.8 秒密集人脸帧后发现：完整原片在约 2–3 秒仍有明显向下低头，不能直接按轻点头验收。原片和完整规范化版本均保留，未覆盖原有致意或其他动作。

基于原片前段制作了一个独立的 4 秒轻点头候选：只选取规范化视频 0–1.32 秒的帧，通过缓入缓出的时间取样往返一次，再加中性姿态停留，避开深低头段。只调整时间顺序和重复已有帧，没有合成人脸或补造中间帧；整段采用固定等比例缩放和平移。倒放/重复可能影响眨眼、呼吸与动作自然度，必须播放确认，不能把候选视为未经剪辑的原始生成视频。

- 静默动作候选：`assets/presenter-v1/motions-v1/prepared/acknowledge-nod-v1.mp4`。
- 口型叠加候选：`outputs/motion-nod-1760-v1/presenter-speaking.mp4`。
- 前段选帧与时间编辑记录：`assets/presenter-v1/motions-v1/nod-candidate-1760-v1/edit-manifest.json`，包括全部 100 帧的来源索引。
- 原片全身/人脸抽帧：`assets/presenter-v1/motions-v1/incoming-1760`；剪辑候选抽帧：`nod-candidate-1760-v1/candidate-face-contact-sheet.jpg`。

候选 100 帧均完成人脸预处理与真实 GPU 口型推理，最终 H.264/AAC 音视频严格解码通过，视频和音频均为 4.0 秒。抽样查看了闭合、张口及点头顶点的人脸结果，人工动作自然度与逐音素口型验收仍未完成。

新四动作顺序预览为 `outputs/motion-review-v2/motion-sequence.mp4`，32 秒、800 帧、无音轨：待机 → 迎宾 → 待机 → 摊手 → 待机 → 轻点头剪辑候选 → 待机 → 告别 → 待机。旧版 35 秒致意预览保留。`Open-Motion-Review.cmd` 已指向新版。

单条复现：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\avatar-2d\Make-Lipsync-Preview.ps1 -Motion acknowledge-nod`。四动作批量入口 `Make-Motion-Previews.cmd` 也已加入该候选；本轮只运行新增点头，不重复生成已通过检查的三条动作。动作库内 `candidate_only=true`、`human_visual_accepted=false`，尚未登记实时服务。

五份原片累计 845 帧完成解码；当前四类说话动作（含剪辑点头候选）累计 675 帧完成离线口型测试。实时动作切换、Fay 联调和目标 GTX 1660 硬件验收状态不变，仍未验证。

## 前一阶段：四份动作视频导入，三类动作口型测试通过

原片及 SHA256 已保存在 `assets/presenter-v1/motions-v1/incoming-*`，原始 724 帧全部通过严格音视频解码。源文件均为 720×1280，平均约 24 fps，容器参考帧率为 60；已统一为恒定 25 fps。各条采用固定的等比例缩放和平移，对齐既有待机首帧的人物高度和站位，保留黑底；没有逐帧拉伸人物或改动脸型。

| 来源编号 | 分配动作 | 规范化结果 | 已完成测试 |
|---|---|---|---|
| 8580 | 迎宾挥手 | 7 秒，175 帧 | 全片人脸预处理、真实口型推理、成片严格解码 |
| 6386 | 告别挥手 | 7 秒，175 帧 | 全片人脸预处理、真实口型推理、成片严格解码 |
| 8687 | 摊手讲解 | 9 秒，225 帧 | 全片人脸预处理、真实口型推理、成片严格解码 |
| 8571 | 低头致意 | 7 秒，175 帧 | 规范化、静默动作预览、严格解码；未送入口型推理 |

两条挥手的迎宾/告别用途根据观察到的节奏分配：8580 更早抬手，6386 收手较晚；原文件保留，未来可调整语义映射。

8571 明显低头，接近礼貌致意，不能视为已取得轻点头素材。先将其作为独立静默致意动作保留，轻点头仍待补拍。参考提示词在 `assets/presenter-v1/motions-v1/轻点头补拍提示词.md`。

### 查看动作结果

- 完整顺序预览：`outputs/motion-review-v1/motion-sequence.mp4`，35 秒、875 帧、无音轨。顺序：待机 → 迎宾 → 待机 → 摊手 → 待机 → 致意 → 待机 → 告别 → 待机。可双击 `Open-Motion-Review.cmd` 用系统默认播放器打开。
- 迎宾口型样片：`outputs/motion-20261103-103654-751-welcome-wave/presenter-speaking.mp4`。
- 告别口型样片：`outputs/motion-20261103-103654-751-goodbye-wave/presenter-speaking.mp4`。
- 摊手口型样片：`outputs/motion-20261103-103654-751-explain-open-palms/presenter-speaking.mp4`。
- 对齐抽帧：`assets/presenter-v1/motions-v1/prepared/alignment-contact-sheet.jpg`。
- 素材清单：`assets/presenter-v1/motions-v1/action-library.json`；汇总：同目录 `validation-summary.json`。

三条口型样片共 575 帧，均通过真实 GPU 推理、FFmpeg 严格音视频解码、OpenCV 独立帧计数；音视频分别为 7/7/9 秒，流时长差均为 0。抽样查看了各条人脸张合及摊手时的全身画面。口型测试使用同一段本机校准语音，按动作长度截取，可能截在句中，用于技术验证，不是最终迎宾/告别话术验收。未进行人工逐音素验收。

原有待机入口也完成 2 秒、50 帧回归，报告在 `outputs/preview-20261103-104017-897`。本机本轮三条短片的推理合成循环约 14.41–16.01 fps，包含短批次开销，尚未达到稳定 25 fps；不能用早期单次长片测量替代本轮数据，也不能外推到 GTX 1660。视频输出编码为 25 fps 不代表计算达到实时速度。

### 重新生成

- 双击 `Make-Motion-Previews.cmd`：重新生成三条动作口型样片并解码检查，自动创建新的时间戳目录。
- 单条示例：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\avatar-2d\Make-Lipsync-Preview.ps1 -Motion explain-open-palms`。`-Motion` 还支持 `idle`、`welcome-wave`、`goodbye-wave`。
- 动作样片各播放一次；该离线工具将测试语音截到动作长度，不会反复循环挥手。致意动作未作为说话底板开放。

当前提供的是离线素材库、手动选择动作的推理入口和解码过的顺序预览。实时事件触发、语音较长时自然回落待机、跨动作平滑切换、打断以及 Fay 实时联调仍未实现或验证。头尾站位对齐不等于无缝切换已经验收。

## 前一阶段：下载、独立环境与本地口型推理完成

已从 LiveTalking 官方仓库下载固定版本源码及其官方文档列出的 Wav2Lip256 权重，另外下载 S3FD 人脸检测权重。独立 `.venv` 已安装 PyTorch 2.9.1+cu128、torchvision 0.24.1+cu128、torchaudio 2.9.1+cu128 与应用依赖；`pip check` 通过，实际安装版本保存在 `requirements.lock.txt`。既有 Fay 环境和 D:/Code/avatar/LiveTalking 未修改。

当前使用用户的 20 秒全身底板完成 500 帧提取、人脸检测和 256×256 人脸预处理，保存在 `runtime/avatars/presenter_v1`。使用本机中文测试语音实际运行神经网络口型推理，生成带声音的 16.44 秒、720×1280、25 fps 样片。没有云端推理调用。

### 查看与复现

- 推荐成片：`outputs/preview-fp16-v2/presenter-speaking-complete.mp4`。
- 人脸抽帧：`outputs/preview-fp16-v2/face-contact-sheet.jpg`。技术验证：同目录 `validation.json`；推理记录：`report.json`。
- 全精度对照：`outputs/preview-v1/presenter-speaking-complete.mp4`。
- 双击 `Make-Lipsync-Preview.cmd`，使用现有底板与固定测试语音生成新的样片和验证报告，每次使用独立时间戳目录，保留旧结果。
- PowerShell 短测：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\avatar-2d\Make-Lipsync-Preview.ps1 -Seconds 2`。完整语音测试省略 `-Seconds`。
- 可指定 `-Precision fp32` 或 `-Precision fp16`，以及 `-BatchSize 4`。默认 auto 仅在 CUDA 计算能力至少 8.0 时采用 FP16，其余采用 FP32；CPU 路径尚未测试。不能将开发机 FP16 数据外推至 GTX 1660。

### 本机实际测试

设备：RTX 5060 Laptop GPU，8 GB 显存。下表为已运行的单次测量，不是稳定实时吞吐承诺。

| 配置 | 视频帧数 | 推理及逐帧合成循环耗时 | 网络推理帧率 | 包含读图、合成和中间编码的循环帧率 | 推理阶段峰值已分配显存 |
|---|---:|---:|---:|---:|---:|
| FP32，batch 8 | 411 | 24.31 秒 | 21.81 fps | 16.90 fps | 5165.98 MiB |
| FP16，batch 4 | 411 | 16.22 秒 | 38.04 fps | 25.34 fps | 1159.11 MiB |

计时不包含首次 avatar 预处理（本机约 33.89 秒）、模型加载、预热和最终 H.264/AAC 封装。两秒入口短测实际用时更高，说明冷启动和短批次开销明显，当前数据不能证明实时服务已经达标。

两份交付成片均通过 FFmpeg 严格音视频解码，OpenCV 独立计数为 411 帧；视频 16.44 秒、音频 16.43 秒，相差约 10 毫秒。初版使用 `-shortest` 封装导致尾帧被裁，原文件保留为 `presenter-speaking.mp4`，修正版另存为 `presenter-speaking-complete.mp4`；新入口已移除该选项。时长一致只证明封装长度，不能代替人工逐音素口型验收。

已抽样查看人脸张合变化。原始全身素材中的人脸较小，放大后细节有限；正式视觉效果仍需播放验收。GTX 1660 6 GB 目标机、WebRTC 流式输出、打断、Fay 实时 ASR/LLM/TTS 联调尚未测试。

### 下载来源与复核

| 内容 | 本地位置 | 大小/固定版本 |
|---|---|---|
| LiveTalking 官方源码 | `vendor/LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da` | commit `c7269433a2b6ecebcd9342445d2ecc882c98b0da` |
| Wav2Lip256 | `models/wav2lip256.pth` | 214,670,409 字节 |
| S3FD | `models/s3fd-619a316812.pth` | 89,843,225 字节 |

来源、SHA256 分别保存在 `source-manifest.json` 和 `models/*-manifest.json`。模型加载使用 `torch.load(weights_only=True)`；坐标 pickle 仅由本地纯数字坐标生成。

本机 Conda Python 目录附带旧版 MSVC DLL，直接导入新版 torch 曾触发 WinError 1114。`tools/windows_runtime.py` 在当前 Python 进程中先加载已安装的 System32 运行库，再导入 torch，CUDA 张量操作及实际推理通过；未替换系统或 Conda DLL。

代码来源：[LiveTalking](https://github.com/lipku/LiveTalking)。原版 [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) 说明其开放结果受非商用限制。当前 256 权重的独立商业授权尚未核实，现阶段仅做本地技术验证；代码许可不能代替模型权重许可。

以下保留素材接收阶段的历史记录；其中“尚未安装/推理”是当时状态，以本节当前结果为准。

## 2026-11-03：首份视频素材接收与预处理

用户提供了即梦生成的基础视频。本轮完成素材检查、保存和预处理，尚未进行口型模型推理。

### 素材检查结果

- 原片：30.048 秒，720×1280，H.264，721 个视频帧，平均约 24.02 fps；容器参考帧率为 60，不能直接当作恒定 60 fps 使用。
- 音轨：AAC、44.1 kHz、双声道；检测均值约 -91 dBFS、峰值约 -80.8 dBFS，接近静音。
- 全片 721 帧成功解码。抽样检查前段人物正面、闭嘴，双手轻叠，双脚完整，黑底构图稳定。
- 约 20 秒后出现全身到半身的构图变化与人物叠影。该后段保留于原片，不加入当前全身底板。
- 当前提取 0–20 秒，生成恒定 25 fps、720×1280、无音轨的全身底板；500 帧完整解码复核通过。
- 早期抽样人脸框约 118–120 像素宽。这份 720p 素材可用于接入测试，最终口型细节需要看实际推理结果；抽帧不等于逐帧人脸/嘴部验收，也尚未验收无缝循环。

### 文件

| 文件 | 用途 |
|---|---|
| assets/presenter-v1/source-jimeng-v1.mp4 | 原片副本，保留用户原始文件与 AI 生成来源元数据 |
| assets/presenter-v1/idle-fullbody-20s-25fps-v1.mp4 | 预处理后的全身底板 |
| assets/presenter-v1/avatar.json | 候选素材清单，尚未登记到运行中的数字人 |
| assets/presenter-v1/video-validation-v1.json | 技术与抽样检查记录 |
| assets/presenter-v1/inspection-v1 | 全身、人脸、过渡区段和处理后抽帧 |
| assets/calibration-speech-16k-v1.wav | 由现有本机中文测试音频转换的 16 kHz、单声道 PCM16 测试音频 |

### 运行准备状态

Fay 独立环境和管理服务已在前一步安装。本目录尚未建立独立的口型推理环境，也未下载口型权重或完成 avatar 预处理。只读核查已有 D:/Code/avatar/LiveTalking 的 models 目录仍只有占位文件。

下一步需要完成口型模型与运行环境，再以当前底板和本地测试音频验证真实口型推理、音画同步和打断。之后才接入 Fay 的真实模型回答、ASR/TTS、知识库与第三方工具。不能将“底板准备完成”描述为“真人数字人已经能够对话”。
