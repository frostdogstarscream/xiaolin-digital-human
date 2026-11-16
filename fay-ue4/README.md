# Fay + UE4 展示舱数字人

独立于上层 Unity 项目的开发目录。目标是 UE4.27.2 本地人物渲染，Fay 编排对话，百炼提供 ASR/TTS/向量及语言模型。目标终端：六代 i5、8GB RAM、128GB 存储、GTX1660 6GB。

## 已有源码与验证范围

- `kiosk/`：本机管理 API、知识库、Fay HTTP/SSE 适配、轮次绑定的 MCP 演示工具、语音采集与播放完成回执。
- `web/`：角色、人设、音色、知识库、显示及调试管理页面。
- `ue4/`：C++ 工程，黑底舞台、显示设置、WebSocket 重连、PCM 播放、口型包络、眨眼、动作和角色接口。
- `tools/maya_export.py`：Maya 选中骨架/网格预检及 FBX2018 导出。
- `tools/ue_import_character.py`：导入独立角色目录并校验骨架、动画和 Morph Target；成功后才登记角色。
- `tools/inspect_fbx.py`：不执行场景内容的 FBX 二进制结构检查。

2026-11-02 的服务及角色清单测试为 **22 passed**，使用模拟 Fay/云服务和 HTTP/WS 测试客户端，覆盖唤醒、取消、迟到工具隔离、播放回执、重连、知识隔离/删除、配置校验、骨骼映射和预览清单隔离。它不证明真实云端联调、UE C++ 编译或物理音频/展示验收通过。

UE4.27.2、VS2019 C++ 工具链和 .NET Framework 4.8 SDK 已安装，编辑器模块已实际编译通过。girl008 已导入并完成带贴图的 UE4 黑底全身预览；已完成本地站姿、面部及动作预览，尚未打包独立 EXE。Fay 已建立独立环境、锁定依赖，并验证管理页面、MCP 管理页和 WebSocket；模型账号与云端联调待完成，使用方法见 [Fay 安装说明](docs/FAY-INSTALL.md)。两个内置诊断配置只是同一个几何校准模型的尺寸变体，不是两个正式人物。

本机双击 `Start-Girl008-Preview.cmd` 可重新打开已导入的人物预览，正常关闭窗口可用右上角关闭按钮或 Alt+F4。实际引擎目录为 `D:\Develop\Epic Games\UE_4.27\UE_4.27`，记录于本机 `runtime/ue-environment.json`；构建脚本使用临时英文目录连接，原工程路径不变。此入口运行的是编辑器的 `-game` 预览，不是成品安装包。

## 开发命令

在本目录执行。现有上层 `.venv` 用于已验证的服务测试；正式交付应建立独立环境并锁定经过联调的版本。

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m uvicorn kiosk.demo:app --host 127.0.0.1 --port 8781
..\.venv\Scripts\python.exe -m uvicorn kiosk.app:app --host 127.0.0.1 --port 8780
```

后两条需分别运行，管理页为 `http://127.0.0.1:8780`。自由对话另外依赖本机 Fay 的 `http://127.0.0.1:5000`，不会静默绕过 Fay。复制 `.env.example` 为本目录 `.env.local` 后配置账号；不共用上层运行库。知识库导入、索引及真实模型调用可能产生云端费用，真实调用范围在联调前另行明确。

Fay 通过 stdio MCP 注册 `python -m kiosk.mcp_stdio`，工作目录必须为本目录；该桥接只暴露查询演示状态、切换演示主题两个工具。正式业务接口替换 `kiosk/business.py`，不得将模拟数据描述为真实业务结果。

## 人物与显示

最新收到的 Maya 人物请看 [girl008 接入检查](docs/girl008-assessment.md)。已新增骨骼面部驱动和独立 FBX 预览流程，不需要先安装 Maya；使用入口、参数和未验证项见 [骨骼预览说明](docs/BONE-PREVIEW.md)。现阶段尚未启用正式人物。

纯黑背景用于展示舱合成，不等同于 Windows 窗口 Alpha 透明。免按键模式需完成现场回声测试后启用；初始为按键模式。UE 按键：空格按住说话、Esc 打断、F10 管理页、Ctrl+Shift+Q 退出。

本地 girl008 预览已验证 UE4.27.2 编辑器模块编译、贴图导入、自然站姿、程序化动作和本机 WAV 口型联动。双击 `Start-Girl008-Preview.cmd`，空格播放校准语音，J/B 切换张嘴/闭眼。

仍需验证：正式打包与材质/LOD 优化、真实 Fay 和云 API、AEC、目标显示器黑底/横竖屏、首音时延、目标硬件帧时间与8小时稳定性。源码完成项、自动测试项与现场验收项分别记录。

## girl008 动作集

已增加待机、说话、挥手、讲解、点头、鞠躬、指向、原地步行和左右转身；默认预览使用 v2 动作集。按键、动态预览与测试证据见 [动作说明](docs/ACTIONS.md)。欢迎、告别复用挥手，仍为本地预览阶段。

## Fay 独立运行入口

双击 `Start-Fay.cmd`，访问 `http://127.0.0.1:5000/`；双击 `Stop-Fay.cmd` 停止。Fay 使用 `.venv-fay` 和 `runtime/fay-local/app`，对话核心待配置模型账号后启动。详见 [安装与验证记录](docs/FAY-INSTALL.md)。
