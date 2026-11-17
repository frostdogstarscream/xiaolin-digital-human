# 全息仓本地 3D 数字人

Windows 原生 Unity 客户端，以黑底展示一个 VRM 人物；Python 本地服务负责知识检索、讲解进度、百炼语音和工具调用。管理界面内置于原生客户端，按 F2 或 F10 打开。

这是第一版开发实现。自动化检查、Windows 实机检查、百炼账号联调和全息仓现场验收分别记录在 [验证记录](docs/VALIDATION.md)。未配置百炼密钥时可以查看人物和管理设置，自由语音对话不可用；固定讲解也需要先生成音频缓存。

## 启动已打包版本

1. 将完整的 `dist/HoloKiosk-Quaternius` 文件夹复制到 Windows 10/11 64 位电脑的可写目录。
2. 双击 `Start-Kiosk.vbs`。它启动本地服务、独立演示接口和原生人物窗口。
3. 按 F2 或 F10，在“语音与AI”中输入自己的百炼密钥并保存。不要把密钥发送到聊天或写入 Unity 资源。
4. 在“讲解内容”中生成讲解缓存，在“知识资料”中建立知识向量索引。这两项会调用百炼服务并消耗账号额度。
5. 默认按住空格讲话，松开后结束录音。Esc 停止当前播报，Ctrl+Shift+Q 退出程序。退出后启动器关闭由它启动的服务。

正常展示隐藏管理台、字幕和聊天窗口；启动与异常提示短暂显示后消失。显示器、比例、位置、朝向和亮度在“人物与显示”中调整。扬声器使用 Windows 默认播放设备；选择后重启客户端。

## 源码开发

固定开发基线：Unity `6000.0.65f1`，标准渲染管线，Windows Mono；ChatdollKit `0.8.16`、UniVRM `0.131.4`、uLipSync `3.1.4`。依赖归档的哈希在 `dependencies.lock.json`。

```powershell
# 在项目根目录执行，需 Python 3.11/3.12 与已激活的 Unity 编辑器
.\tools\Setup.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\tools\Build-Windows.ps1 -UnityEditor 'D:\Develop\Unity\6000.0.65f1\Editor\Unity.exe'
.\tools\Package.ps1
.\Start-Kiosk.ps1
```

`Setup.ps1` 安装 Python 依赖并获取开源 Unity 组件；Unity 引擎和许可由开发者单独安装、激活。现场使用打包版无需安装 Python 或 Unity 编辑器。仅调试后端时运行 `Start-Kiosk.ps1 -ServicesOnly`。

## 配置与内容

- 预设“亲切接待、正式讲解、技术介绍”三个角色。名称、身份、性格、回答长短、欢迎语、音色、语速、动作频率和知识库均可改。
- 默认模型：`qwen-plus`、`fun-asr-realtime`、`cosyvoice-v3-flash`、`text-embedding-v4`；默认音色 `longxiaochun_v3`。模型在管理台设置，地域和服务地址在 `.env.local` 配置。
- 资料支持 TXT、MD、DOCX、文字 PDF，单文件最多 15 MB / 50 万字，PDF 最多 300 页。扫描 PDF 提示先转文字。未建立向量索引时使用本地词匹配检索。
- 三个主题的标识固定为 `overview`、`workflow`、`value`；标题和逐句稿件可改。每行一句，最长 300 字。被打断后保留当前句，继续讲解会重播该句。
- 导入 VRM 后先预览并核对授权，再启用。要求有效人形骨骼、眨眼和 A/I/U/E/O 五个口型，文件小于 150 MB，蒙皮网格顶点不超过 30 万。预览被拒绝时保留旧人物。
- 默认人物是 pixiv 的公开 VRM 示例模型，非定制职业女性。源信息、模型授权字段和组件许可见 `licenses/`。

设置和讲解进度存于 `runtime/avatar.sqlite3`；提取后的资料在 `runtime/documents`，完整 PCM 音频缓存在 `runtime/audio`，服务日志在 `runtime/logs`。应备份整个 `runtime`，升级时保留 `.env.local` 和用户数据。新导入的 VRM 会复制到 Unity 的用户数据目录（`%USERPROFILE%/AppData/LocalLow/HoloKiosk/全息仓数字人/Avatars`），迁移电脑时需重新导入模型。

## 交互边界

免按键模式使用麦克风音量检测和 ASR 文字确认插话。当前没有内置软件声学回声消除；需要带 AEC 的麦克风/声卡或经过验证的系统音频链路。管理台的“已验证回声消除”是现场测试声明，不会自动开启硬件 AEC。未通过现场测试时使用按键模式。

回答通过百炼流式接口接收；为避免工具调用前误报成功，先完成工具判定和回执，再分句合成与流式播放。因此实际首音延迟必须实测。断网可播放已缓存的固定讲解，未缓存内容及自由问答会明确报错。

演示接口是真实运行的本地 HTTP 服务，其统计数据是模拟数据。真实业务接入点在 `service/business.py`。接口协议、事件和扩展方式见 [协议说明](docs/PROTOCOL.md)，现场检查步骤见 [验收清单](docs/ACCEPTANCE.md)。

## Quaternius 动作版

待机与交谈已接入真实人形动作，管理台可预览完整 42 项动作。操作、验证和来源见 [动作接入说明](docs/QUATERNIUS.md)。旧版交付目录保留。

## 小霖 2D 真人全身实时数字人（1080×1920 @ 50 fps DiT-v2）

针对真人全身竖屏素材（`1080×1920`）构建的高真实度、低延迟 WebRTC 实时语音数字人方案，支持云端单张 Tesla T4 与局域网 RTX 4090 双端 `50 fps` 实时渲染：

- [小霖 DiT-v2 嘴部与全下半脸专人权重生成方法](docs/小霖DiT-v2嘴部与全下半脸权重生成方法_20261116.md)：CVPR-2025 `Sonic` 512×512 离线扩散母带合成 → 亚像素上颅骨刚性对齐 → `256×256` 双基准（闭嘴微笑 + 高清真牙）ResUNet + PatchGAN 专人轻量模型蒸馏与 `rife-dit-v2` 50fps 全身缓存构建全流程。
- [小霖双引擎（Qwen / Fay）接入、免密管理台与 1080×1920 竖屏字幕前端说明](docs/小霖双引擎Fay接入与竖屏字幕前端部署_20261117.md) & [云端 T4 双引擎蓝绿部署套件](deploy/t4-cloud/dit-v2-fay/README.md)：极速语音直连（自动同步 Fay 人设与在线 MCP 工具）↔ Fay 完整认知引擎零断流热切换、免密 `/fay/setting` 与 `/Page3` 同源控制台，以及 `1080×1920` 竖屏沉浸式双行实时字幕前端。
- [小霖 4090 独立部署与启动](docs/小霖4090部署与启动_20261113.md) & [云端 T4 / 4090 DiT-v2 部署说明](deploy/t4-cloud/dit-v2/README.md)：局域网 `Open-Xiaolin-4090-DiTv2.cmd`（`18775` 端口 50fps）一键启动与云端 T4 蓝绿无损切换方案。
- [小霖数字人技术与部署交接](docs/数字人技术与部署交接_20261112.md)：整体服务拓扑、网关协议、唤醒 ASR、知识/记忆协调与运维规范。
