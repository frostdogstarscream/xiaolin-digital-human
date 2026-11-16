# Fay 大小模型协同：Flash 占位部署

## 2026-11-04：角色推理配置已启用

两个角色仍使用 OpenCode Go `deepseek-v4.1-flash`，现已分别绑定推理参数：主问答 `thinking.type=disabled`、`reasoning_effort=low`；后台执行 `thinking.type=enabled`、`reasoning_effort=medium`。DeepSeek 官方将 medium 映射为 high；关闭思考优先于 low，主问答实际不进行低强度思考。

参数保存在 system.conf 的 `llm_generation:small` / `llm_generation:big` 独立段中，按模型 ID 和基础地址匹配。参数从下一次请求读取；后续更换模型或服务地址时，旧推理参数不会自动应用到其他模型。大小模型原生工厂、`model=llm` 代理默认参数和配置页的已保存模型文字流测试均读取主问答设置；代理调用者显式提供的参数优先。

配置页 <http://127.0.0.1:8766/models> 的协同状态会分别显示思考开关、请求的 effort 及 medium→high 映射。启动后正式 health 已核实两个角色配置，`model_state=ready`、Fay 核心运行、WebRTC 已连接、百炼 TTS 仍为 Cherry / WebSocket PCM 流式输出。

验证结果：8 项本地回归通过，包含真实 LangChain 序列化后的两个角色 HTTP 请求、热更新、模型/地址切换隔离及原有密钥/TTS保护；隔离的原生后台执行及完成回调通过两次真实 Go 调用，两个角色参数正确，返回 DUAL_TEST_OK。该测试不注册正式工具、不写正式记忆，不调用 TTS。

另在现有展示会话执行一次正式问答“你叫什么名字”，回复“我叫小霖。”，首个回答文字 4.527 秒，首个播放回调 5.899 秒，TTS 首块 PCM 0.623 秒，生成 21 个说话帧。它验证正式流程可用，不是完整延迟基准，也未验证物理麦克风或外放听感。此前接口短问题的 0.88 秒是抽样中位数，不是正式开口时延保证。

本轮记录：`role-reasoning-activation-2026-11-04.json`、`role-reasoning-collaboration-validation-2026-11-04.json`、`role-reasoning-dialogue-validation-2026-11-04.json`。下文保留 2026-11-03 的初始部署和验证记录。

配置日期：2026-11-03。配置入口：<http://127.0.0.1:8766/models>。

本轮按现有服务把“v4lash”解释为当前已经验证的 OpenCode Go `deepseek-v4.1-flash`。两个角色暂时使用同款云端模型，通过 Fay 原生角色工厂及执行管理器分工。

| 角色 | 当前配置 | 职责 |
| --- | --- | --- |
| 主问答 `small` | `deepseek-v4.1-flash` | 日常问答、有工具时的判断分流、后台结束后的结果整理与流式回复 |
| 后台执行 `big` | `deepseek-v4.1-flash` | 原生 `ExecutionManager` 后台工具执行循环 |

主问答仍使用 `gpt_*`，后台执行使用独立保存的 `big_model_engine`、`big_model_base_url`、`big_model_api_key`。占位启用时复制当前已经保存的主模型配置；之后修改主模型，不会暗中改变后台模型的服务地址和密钥。

页面新增协同状态及两个操作：“使用主模型占位并启用”与“关闭协同”。这些操作使用原有本机访问限制；API 和页面仅返回模型、地址及模式，不回显密钥。关闭协同会清空原生模式开关 `big_model_engine`，保留后台地址与密钥。

## 生效范围

- `big_model_engine` 已非空，原生 `_is_single_model_mode()` 返回 False。
- 普通聊天在无工具时仍直接回答，不强制串行请求两个角色。
- 当前实际业务工具数为 0，知识库与关联记忆维持原有关闭状态。接入真实业务工具后，工具分支才会在实际使用中调度后台角色。
- 两角色共用同款模型是配置占位，不代表更大参数量或已获得性能提升；之后可独立替换后台模型。
- 两角色沿同一 conversation ID 设置 OpenCode 会话头，避免后台回填切换路由会话。
- 百炼实时 TTS、Cherry 音色、FunASR、小霖唤醒词、Wav2Lip 和四动作未变更。

## 验证

`check_generic_llm.py` 七项配置与 HTTP 回归通过，包含后台配置快照、主模型更换后后台保持独立、关闭协同及密钥不回显。

`check_collaboration.py` 加载安装版本的原生执行管理器与原生完成回调，使用隔离的只读测试工具和流输出接收器。它不注册生产工具、不写业务记忆、不触发 TTS。

模拟测试通过；真实模型测试使用两次 OpenCode Go 请求：后台角色完成工具结果判断，主问答角色流式整理结果。共执行一个本地只读工具，最终回复含 `DUAL_TEST_OK`，总耗时约 8.655 秒。验证了后台线程、同用户重叠任务拒绝、原会话回填、结束标记及完成结果消费。

该测试证明模型工厂、后台执行和完成回调可运行；正式业务工具的权限、参数和端到端业务流程仍需在接入工具时另测。

服务重启后，普通问答到百炼 PCM、LiveTalking 口型输出也通过，沿用原展示会话。单次测试首个回答文字约 9.141 秒，首个播放回调约 10.632 秒；服务端内部记录的 `route=direct`、`tool_count=0`，说明普通问答未被强制送入后台工具流程。该结果不表示协同已带来提速，亦未测物理麦克风或外放听感。独立记录为 `collaboration-dialogue-validation.json`。

结果文件：`collaboration-activation.json`、`collaboration-mock-validation.json`、`collaboration-real-validation.json`。

复现（PowerShell，项目根目录）：

```powershell
& './fay-ue4/.venv-fay/Scripts/python.exe' './avatar-2d/tests/check_generic_llm.py'
& './fay-ue4/.venv-fay/Scripts/python.exe' './avatar-2d/tests/check_collaboration.py'
# 下面命令使用已保存密钥，进行两次真实模型调用：
& './fay-ue4/.venv-fay/Scripts/python.exe' './avatar-2d/tests/check_collaboration.py' --real
```
