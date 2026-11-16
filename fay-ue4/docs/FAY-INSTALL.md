# Fay 本机安装与使用

2026-11-03：Fay 框架已在本机独立环境中安装，管理界面和接口已启动并验证。

## 打开与关闭

- 管理界面：<http://127.0.0.1:5000/>
- MCP 管理：<http://127.0.0.1:5010/Page3>
- 双击 `fay-ue4/Start-Fay.cmd` 启动并打开管理页面。已运行时复用现有进程。
- 双击 `fay-ue4/Stop-Fay.cmd` 停止本次启动器记录的 Fay 进程及其子进程。
- 关闭浏览器不会停止后台服务；当前未设置开机自启或 Windows 服务。

## 实际安装位置

| 内容 | 路径，相对于 fay-ue4 |
|---|---|
| 独立 Python 3.12.4 环境 | `.venv-fay` |
| 保留的原始源码 | `vendor/Fay-source` |
| 本机运行副本 | `runtime/fay-local/app` |
| 模型、语音连接设置 | `runtime/fay-local/app/system.conf` |
| 人设与交互设置 | `runtime/fay-local/app/config.json` |
| 数据库、记忆、音频与内部日志 | 运行副本中的对应目录 |
| 每次启动的 stdout / stderr | `runtime/fay-local/launch-时间戳` |
| 进程记录 | `runtime/fay-local/process.json` |
| 完整依赖锁定 | `fay-requirements.lock.txt` |
| 上游兼容约束 | `fay-constraints.txt` |

安装过程依据现有源码及其 requirements.txt，补齐全部 33 项直接依赖。为适配该源码，固定了 LangChain/LangGraph、MCP 与 Pydantic/Starlette 的兼容组合。PyTorch 使用 CPU 版，Fay 环境与后续 2D 口型推理环境分开。

## 已验证的内容

- `pip check`：`No broken requirements found`。
- 33 项直接依赖均满足源码声明的版本条件；Flask、PyAudio、Azure Speech、LangChain OpenAI、LangGraph、MCP、Chroma、Sentence Transformers 和 PyTorch 导入通过。
- 管理首页、Vue JS、页面 CSS、MCP 管理页实际 HTTP 200。
- 10002 数字人 WebSocket、10003 管理 WebSocket 的握手及 ping/pong 通过。
- 5000、5010、10002、10003 均仅监听 `127.0.0.1`。
- 浏览器已实际显示 Fay 消息、人设和 MCP 导航。
- 启动、停止、重启以及 Windows PowerShell 重复启动识别均已验证。
- 汇总证据：`docs/fay-install-validation-20261103.json`。

## 当前待配置内容

框架管理服务已运行；对话核心当前未自动启动，状态接口返回 `status: false`，这与管理服务运行状态不同。

运行配置中的 LLM、ASR、TTS、Embedding 账号尚未接入。模型 API 暂指向未启用的本机地址，不使用源码附带的公共配置中心、共享账号，也未发起模型或计费请求。配置完成后再启动对话核心并分别验证文本回答、语音识别、语音合成、检索及工具调用。

本轮仅安装 Fay，LiveTalking、2D 口型权重和真人素材尚未在本项目部署。后续按真人 2D 路线接入。

## 本机运行副本的适配

原始源码保留；运行副本仅做本机安装所需适配：网络监听限制为回环地址、保留历史日志和音频、移除按端口清理其他进程的退出行为、关闭未配置的内部 MCP SSE 自动启动。MCP 管理页仍正常运行。

文件哈希与适配清单位于 `runtime/fay-local/deployment.json`。启动器会清除子进程继承的配置中心及模型密钥环境变量，仅使用此安装自己的本地配置。没有修改系统环境变量。

## 复核命令

在 `fay-ue4` 目录执行：

```powershell
.\.venv-fay\Scripts\python.exe -m pip check
.\.venv-fay\Scripts\python.exe tools\check_fay_install.py
.\Start-Fay.ps1
.\Stop-Fay.ps1
```

上面命令已在本机执行；`check_fay_install.py` 只检查依赖、管理服务与 WebSocket，不调用模型、不录音、不写业务数据。
