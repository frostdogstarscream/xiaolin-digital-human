# 小霖口型后端评估

独立地址：<http://127.0.0.1:8768/>。双击 `Start-MuseTalk-Eval.cmd` 启动和打开页面；`Stop-MuseTalk-Eval.cmd` 只停止本实验进程及其子进程。

本实验对比 Wav2Lip 与 MuseTalk 1.5，复用当前小霖和迎宾挥手、告别挥手、摊手讲解、点头的实际姿态帧。原正式入口 8766、Fay 5000、FunASR 8780 与 LiteAvatar 8767 独立运行；实验不会启动/停止这些服务、修改其配置或写入实时 TTS 通道凭据。

## 使用

1. 打开页面，等待模型就绪，点击“连接音视频”。
2. 选择短语音或含停顿的长语音，点击待机说话或动作按钮。
3. 选择另一后端，点击“切换后端并连接”。切换时卸载旧后端并重新建立单会话。
4. “打断 / 停止”取消音频和动作、丢弃旧代音频；说话时也可单独切换到点头。
5. 对照区选择动作后打开长语音对照：左为 Wav2Lip，右为 MuseTalk，含全身及面部放大两个视频。

浏览器首次播放声音可能需要点击“开启声音”。该页面没有麦克风采集，也不发送模型问答或云 TTS 请求；语音来自冻结的本地文件。打开其他评估窗口会重新连接本实验会话，不接管正式页面。

## 固定输入与模型

- LiveTalking 源码复用 `avatar-2d/source-manifest.json` 固定的 `c7269433a2b6ecebcd9342445d2ecc882c98b0da`，不修改 vendor。
- 官方权重版本、大小和 SHA256 见 `models/manifest.json`，包括 MuseTalk 1.5、Whisper Tiny、SD VAE、BiSeNet 和 ResNet18。所有大文件对照官方 LFS 摘要验证。
- 依赖固定在 `requirements.lock.txt`；PyTorch 2.9.1、torchvision 0.24.1、torchaudio 2.9.1 均为 CUDA 12.8 版本。本机首次部署把已有已验证包物理复制到新环境，未使用共享链接；记录见 `docs/torch-provenance.json`。
- `fixtures/manifest.json` 冻结短语音 2 秒和长语音 16.28 秒的来源、摘要、PCM 16 kHz 单声道格式。长语音由现有三个合成片段与固定停顿组成，没有重新调用云服务。
- `cache/` 仅保存本实验预处理。675 个姿态帧逐一对应原图、原坐标；MuseTalk 专用潜变量及下颌融合遮罩不会覆盖原文件。
- 待机说话沿用正式入口的迎宾中性首帧；四个动作按原时间轴播放一次，结束保持该动作自己的末帧。点头仍使用原来的早段剪辑候选，不把原素材尚待人工确认的动作标为已验收。

## 实现边界

`service/engine.py` 复用现有 Presenter 的音频队列、动作时间轴、原生 HumanPlayer 输出和打断代号。Wav2Lip 用 Mel 特征；MuseTalk 用原生 Whisper 特征、逐姿态的潜变量和融合遮罩。每一帧使用相同身体姿态对应的人脸数据；20 ms 音频帧与首尾事件保持原接口。

`service/server.py` 使用自己的 RTCManager/会话管理器实例进程、固定音频播放接口与运行目录。它没有导入 Fay 应用桥接，也没有创建或覆盖正式 `realtime-ingress.json`。模型推理全部使用本地权重，启动后关闭模型联网查找。测试以 100 ms PCM 块实时投递，不能把离线生成快慢当成 WebRTC 输出帧率。

## 报告与复验

- `outputs/comparisons/`：10 组条件 × 全身/放大两视图，共 20 个左右对照视频。
- `outputs/evaluation-report.json`：固定输入、动作帧一致性、原身体区域不变检查、冷启动/预处理、离线报告与实时测试汇总。
- `outputs/realtime-validation.json`：两个后端顺序运行的实际 WebRTC 接收记录、首个推理口型帧 P95、持续帧率、播放期间峰值积压及显存。

重新运行，均在实验目录中使用 `.venv/Scripts/python.exe`：

```powershell
python tools/render_comparisons.py --backend wav2lip
python tools/render_comparisons.py --backend musetalk
python tools/assemble_results.py
# 先运行 Start-MuseTalk-Eval.ps1；测试会接管 8768 的实验会话
python tests/check_realtime.py --seconds 300
python tools/assemble_results.py
```

两个后端每个至少 300 秒，顺序测试；模型预热后再开始稳定性采样。门槛为实收约 25 fps、无持续积压，候选首帧 P95 增幅不超过 200 ms。显存数值为本实验 PyTorch 分配峰值，包含该进程模型和推理张量，不代表整机所有进程显存。冷加载、首次预处理及含视频编码的离线速度单独记录，不混入实时门槛。

画质、逐音素口型和人物一致性需要观看对照视频确认。报告持续标记 `USER_REVIEW_REQUIRED`，不会凭自动检查自动切换正式后端。达不到实时门槛时保留结果，正式入口继续使用 Wav2Lip。

首次重新部署可使用 `Setup-MuseTalk-Eval.ps1`，可通过 `-Python` 选择 Python 3.12 路径，`-ProxyUrl` 仅为该安装进程指定已有代理。需要约 10 GB 可用空间；脚本只安装本实验虚拟环境和缓存。

来源：[MuseTalk](https://github.com/TMElyralab/MuseTalk)、[官方模型下载清单](https://github.com/TMElyralab/MuseTalk/blob/main/download_weights.bat)、[LiveTalking](https://github.com/lipku/LiveTalking)。
