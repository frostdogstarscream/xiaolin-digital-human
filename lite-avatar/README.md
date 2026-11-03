# Fay + LiteAvatar 独立实验版

分支：`feature/fay-liteavatar`。页面：<http://127.0.0.1:8767/>。

选用的形象来自用户指定的 [LiteAvatarGallery 20250612 目录](https://modelscope.cn/models/HumanAIGC-Engineering/LiteAvatarGallery/file/view/master/20250612/avatar.md?status=1)，完整 ID：`20250612/P1VtV9PVTqDj7CiZx2CCme2A`。这是 **LiteAvatar**，人物驱动使用 [HumanAIGC/lite-avatar](https://github.com/HumanAIGC/lite-avatar)，本实验服务不导入或运行 LiveTalking、Wav2Lip。

## 启动与使用

双击 `Start-LiteAvatar.cmd`，或在工作区执行：

```powershell
.\lite-avatar\Start-LiteAvatar.ps1 -OpenBrowser
```

启动器复用已安装的 Fay（5000）和本机 FunASR（8780），另外启动 LiteAvatar（8767）。原数字人服务和入口（8766）保留。停止实验版使用 `Stop-LiteAvatar.cmd`；它只停止实验服务及自身编码子进程。

- 默认“通义问答”：问题经 Fay 调用现有百炼模型，回答转为语音后交给 LiteAvatar 渲染。
- “直接播报”：输入文字，Fay 合成语音后生成有声口型视频。
- 点击“开启语音唤醒”，允许麦克风后说“小霖小霖”。沿用既有欢迎词、同音容错与 60 秒唤醒窗口。页面隐藏、断线、关闭麦克风和打断会释放录音。
- “打断 / 停止”停止当前播放、取消过期生成并清理待播队列；“全屏展示”显示人物。
- 当前使用该预训练形象自带的背景与姿态。自定义迎宾挥手、告别挥手等需要另外适配该形象。

## 当前链路与限制

本机麦克风 → 本机 FunASR → 唤醒判断 → **Fay / 百炼问答与 TTS** → 本机语音文件 → **LiteAvatar Paraformer 特征 / audio2mouth / 人脸渲染** → 分段 MP4 → 浏览器按顺序播放。

本实验版先验证所选预训练形象与 Fay 的完整接入，采用音频片段生成后播放，**尚未接通端到端流式音频 / WebRTC 输出**。界面与健康接口明确显示这个状态。原版百炼实时 TTS 的通道属于原数字人服务，本实验用户 `LiteAvatarExperiment` 使用 Fay 的文件语音接口，两路按用户名隔离。

Fay 的既有凭据只在原配置中读取，没有复制到新目录。实验版没有接入业务知识库。

## 环境与来源

- 独立目录及环境：`lite-avatar/.venv`。只读复用 `avatar-2d/.venv` 中已安装的 GPU / 通用运行库，新增和兼容版本安装在实验环境中，不改原环境。
- 官方源码固定在 `5b7ec850945e03d56fb290b05fb68440c359fa86`；供应商代码保存在 `vendor/lite-avatar`，未修改。
- 所选形象包约 24.7 MB；推理权重 `model.pb` / `model_1.onnx` 共约 1.065 GB。下载按官方文件修订号固定，并校验大小及 SHA256。清单见 `source-manifest.json`。特征提取器未使用 LM 解码，未下载 `lm.pb`。
- Windows 兼容处理只在实验进程中执行：加载系统 CRT、为 Python 3.12 导入 setuptools 的 distutils，并用相对路径访问模型和图片。
- 人脸渲染使用现有 NVIDIA GPU；特征提取与 ONNX audio2mouth 使用 CPU。源码许可见 `research/LICENSE`，形象和权重来源见官方 Gallery。

在当前工作区恢复环境可运行 `Setup-LiteAvatar.ps1`。完整实际版本记录在 `requirements.lock.txt`，实验环境新增版本记录在 `requirements.addons.lock.txt`。

## 已运行验证

- `tools/probe_engine.py`：真实 2 秒中文音频生成 50 帧、25 FPS 有声视频；本次特征约 0.32 秒，渲染及编码约 0.93 秒，CUDA 人脸渲染。样片在 `outputs/first-speech/speaking.mp4`。
- `tests/check_integration.py`：真实本机 ASR、未唤醒拦截、完整欢迎词的多个片段、真实 Fay/百炼简短问答、LiteAvatar 视频和音频解码、关闭唤醒及打断。结果见 `docs/integration-validation.json`。该脚本通过协议模拟播放完成回执，和浏览器实际播放证据分开记录。
- 浏览器实际打开实验页面并提交播报，观察到视频 `readyState=4`、`ended=true`、1024×1408，收到真实播放开始/结束回执；见 `docs/browser-validation.json`，截图在 `outputs/browser-preview.jpg`。
- `node tests/check_voice_listening.cjs`：静音丢弃、语音结束识别、播放期间暂停处理、恢复聆听及设备释放。

以上耗时为本机单次测量，不能当作其他文本或现场环境的延迟保证。实际麦克风识别准确率、扬声器听感、现场回声及人物效果的人体验收仍需用户确认。
