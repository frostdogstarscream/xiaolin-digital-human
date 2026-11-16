# 验证记录

日期：2026-11-02。此文档随实际检查更新。

开发电脑：Windows 11，Intel Core Ultra 7 255HX，NVIDIA GeForce RTX 5060 Laptop GPU（驱动 32.0.16.1047），另有 Intel 核显和虚拟显示适配器。本机检查不能替代现场 GTX 1660 Super 的帧率验收。

| 检查 | 当前结果 | 证据与边界 |
|---|---|---|
| Python 自动化测试 | 21 项通过 | `python -m pytest -q`；配置、资料、接口、取消、缓存、讲解确认、旧连接失效及本地模拟 ASR/TTS/LLM 协议 |
| Python 服务 EXE 打包 | 通过真实进程检查 | PyInstaller 6.13.0；主服务、演示服务均实际启动，HTTP 配置读写/资料导入/主题切换以及 WebSocket 缓存 PCM 传输和播放确认通过，见 `service-smoke-report.json` |
| Unity 客户端编译 | 通过 | Unity 6000.0.65f1；Windows x64 / Mono / D3D11；最终构建报告 0 错误、0 警告，输出 `Windows/HoloKiosk.exe` |
| 原生人物画面、管理台 | 开发机实机通过基础检查 | 实际独立 EXE 显示黑底、完整全身人物和眨眼；已修正人体根节点导致的裁切、管理面板绘制顺序；中文管理页与 F10 入口可用 |
| 口型与本地音频链路 | 开发机实机通过基础检查 | 独立测试数据使用 Windows Huihui 中文语音，非百炼：PCM 23.885 秒，原生播放完成回执约 24.202 秒；播报中观察到嘴型变化。未替代扬声器听感、精细口型或现场声学验收 |
| 一键启动与服务退出清理 | 通过 | 从交付目录的 `Start-Kiosk.vbs` 实际启动原生 EXE 和两个冻结服务；Ctrl+Shift+Q 正常退出后 5 秒检查，三个进程均退出，8765/8766 端口释放 |
| 原生章节暂停与恢复 | 通过本地缓存测试 | 管理台开始、暂停、继续；暂停和恢复初始位置均为第 1 句，随后按播放确认推进到第 2 句及结束；测试使用隔离的 Windows 中文 PCM 缓存 |
| 百炼真实 ASR / LLM / TTS / Embedding | 待账号联调 | 当前未配置密钥；协议测试使用本地模拟服务 |
| 现场回声消除 | 待现场检查 | 依赖外部 AEC 音频链路；默认按键讲话 |
| GTX 1660 Super、全息仓显示 | 待现场检查 | 当前开发电脑不能代表仓内机器 |
| 500 ms 打断、3 s 首音 | 待测 | 目标值，未给出性能保证 |
| 连续 8 小时稳定性 | 待测 | 本轮尚未完成 |

测试存在一个第三方 Starlette/AnyIO 弃用提示，不影响当前测试结果。基础人物采用 pixiv 公开示例模型，授权信息保存在 `licenses`，不代表已完成参考图的职业女性建模。

## 构建与运行证据

- 编辑器安装程序完整长度 `4075509384` 字节，MD5 与官方发布信息一致：`e9d4c15a106e560657f08d8ca9570226`；Windows Authenticode 状态 `Valid`，签署者 Unity Technologies SF。
- 组件版本与原始归档校验见 `dependencies.lock.json`、`upm-sources.lock.json`；独立程序的构建摘要为 `Windows/build-report.txt`。
- `service-smoke-report.json` 记录重新打包后的五项真实 HTTP/WebSocket 检查；所有测试的云端调用次数为 0。
- 原生测试日志在开发目录 `runtime/logs/native-smoke.log`；测试数据位于 `runtime/native-smoke`，没有复制到正式交付包。
- `native-smoke-report.json` 记录原生检查范围；`native-avatar.png` 是实际程序保存的画面。
- F2 在当前开发电脑被其他悬浮菜单占用；可使用 F10 或 Ctrl+Alt+M。退出快捷键为 Ctrl+Shift+Q。
- 后续 Quaternius 版本已将待机与交谈替换为导入的人形动作，并接入 42 项手动预览；42 项原生播放检查和 5 项状态/骨骼运动检查通过，详见 `QUATERNIUS.md` 和 `quaternius-animation-smoke.json`。其余语义动作保留原有程序曲线。其他 VRM、现场显示和长时间稳定性仍需验证。
