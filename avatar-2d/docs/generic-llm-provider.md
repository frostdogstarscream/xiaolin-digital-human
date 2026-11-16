# Fay 通用大模型接口

配置入口：<http://127.0.0.1:8766/models>。Fay 的消息页和人设页也有“大模型配置”链接。这个独立页面不会创建 WebRTC 会话或接管数字人画面。

## 使用

1. 选择百炼、OpenCode Go 或自定义 OpenAI 兼容接口。
2. 填写接口基础地址、模型 ID 和该服务自己的 API Key。
3. “测试文字流”发送一次简短的连接测试，显示首字和完整响应耗时；不保存、不写 Fay 对话历史、不触发 TTS。密钥在测试后保留在当前密码框，便于下一步保存，页面不读取已保存密钥。
4. “保存并启用”保存本机配置，从下一次大模型请求生效；正在输出的请求继续使用其开始时的配置。不需要再次重启。

OpenCode Go 预设（核对日期 2026-11-03）：

| 项目 | 值 |
| --- | --- |
| 协议 | OpenAI Chat Completions，`stream=true` |
| Base URL | `https://opencode.ai/inference/go/openai/v1` |
| 模型 ID | `deepseek-v4.1-flash` |
| 最终请求路径 | `/chat/completions` |

依据：[OpenCode Go 官方文档](https://opencode.ai/v2/docs/console/go/)。官方将 Go 定位为编程代理服务，数字人使用需要确认套餐适用范围；部分 DeepSeek 权限依赖账号的区域设置。应用不伪装成其他客户端，也不代改账号隐私设置。

自定义支持其他 Chat Completions 服务与本机兼容服务。Base URL 可保留代理路径；误贴完整 `/chat/completions` 地址会去掉该后缀。外部服务使用 HTTPS，本机回环地址可使用 HTTP。模型名允许斜线、冒号等，例如 `org/model:tag`。无需认证的本机服务可填 `EMPTY`。Anthropic Messages、Responses 等其他协议需要另行适配。

## 密钥与语音隔离

- 实际主问答仍写入 Fay 原生 `[key]` 的 `gpt_base_url`、`gpt_model_engine`、`gpt_api_key`。
- 各服务的配置保存在同一个被 Git 忽略的本机 `system.conf` 的 `[llm_profile:...]` 分组。切回服务可继续使用其已存密钥；更换地址必须重新填写该地址的密钥。接口返回和页面不回显密钥。
- 原共享的百炼密钥先迁移到 `bailian_tts_api_key`，百炼地址独立固定到 `bailian_tts_base_url`。更换问答模型不会把 OpenCode 密钥送到百炼，也不会覆盖百炼音色、实时语音开关等配置。
- Fay 主问答对象改为每次请求创建，避免导入模块时缓存旧模型。大小模型工厂、后台工具执行和原生 `model=llm` 代理都保留兼容。另行配置的 `big_model_*` 不覆盖。
- OpenCode 请求带真实 `User-Agent: Fay-DigitalPresenter/1.0` 和哈希后的会话标识，不发送用户名原文。
- FunASR、唤醒词、动作、Wav2Lip、对话数据和关联记忆开关保持原设置。

## 本轮验证

- `check_generic_llm.py` 五个回归测试全部通过：服务切换及回切、TTS 与其他设置保留、禁止跨地址隐式复用密钥、页面本机访问限制、无保存的 SSE 连接测试、实际 LangChain SSE 适配与下一请求读取新模型/密钥。
- 自动连接回归通过：无须手动连接按钮，自动重连及录音交互保持。
- 真实浏览器调用当前百炼模型：返回“连接成功。”，首字约 453ms，总耗时约 533ms。这个单次结果只表示直接文字接口探测，不是 Fay 完整问答或数字人端到端延迟。
- 服务启动后确认 Wav2Lip ready、FunASR ready、百炼实时 TTS/Cherry 保留、唤醒词“小霖小霖”保留。
- 初次交付预设后，用户提供密钥，已完成 OpenCode Go 真实连接与配置启用。简短文字流首字 2337ms、总耗时 2345ms；完整 Fay 问答首字 5.821s、首个播放回调 7.407s、TTS 首个 PCM 0.745s。百炼返回 11 个 PCM 块、LiveTalking 新增 85 个说话帧，原展示会话保持。原百炼 TTS 配置经逐项比较未变。以上是单次观测，不含物理麦克风或扬声器听审验收。详见 `opencode-go-activation.json` 和 `opencode-go-dialogue-validation.json`。

复现命令（项目根目录，PowerShell）：

```powershell
& './fay-ue4/.venv-fay/Scripts/python.exe' './avatar-2d/tests/check_generic_llm.py'
node './avatar-2d/tests/check_auto_connect.cjs'
```

安装补丁：`avatar-2d/tools/install_generic_llm.py`，重复运行不会重复插入源码。补丁仅影响本地部署副本，原始上游保留；代码修改前的副本保存在 `avatar-2d/runtime/llm-provider-patches/`，不备份密钥文件。
