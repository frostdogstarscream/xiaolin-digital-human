# Quaternius 动作接入

日期：2026-11-02。

新版目录：`dist/HoloKiosk-Quaternius`。双击其中 `Start-Kiosk.vbs` 启动。旧版 `dist/HoloKiosk` 保留。

## 自动动作与手动预览

| 场景 | 动作 | 行为 |
|---|---|---|
| 待机 | Idle_Loop | 连续循环 |
| 自由问答 / 固定讲解 | Idle_Talking_Loop | 按角色的动作频率选择是否启用，启用后持续到状态变化或停止 |
| 聆听、思考、欢迎、指引、结束 | 原有基础动作 | 保留现有语义映射 |
| 其余动作 | Quaternius 动作库 | 管理台手动选择和播放，不自动加入接待流程 |

按 F10 → 人物与显示 → Quaternius 动作库，使用“上一个动作 / 下一个动作”选择，然后点“播放选中动作”。共有 42 项，包括交互、坐姿、正式步行等。循环动作预览 8 秒，非循环动作播完并留出淡入时间；可随时点“结束动作预览”。预览结束后恢复当前的待机、聆听或交谈状态。Esc 停止播报并返回待机。

使用不带 `_RM` 的 Unity FBX，Humanoid 重定向，关闭根运动，根位移与旋转烘焙到姿势。步行是原地动作；坐姿没有自动配套椅子。T Pose 是参考姿势，不作为业务动作。

## 验证

- Unity 6000.0.65f1 Windows x64 构建成功，0 错误、0 警告。
- 实际独立 EXE 加载当前 Sample.vrm，42 项动作逐项检查 Animator 参数及实际播放片段，全部通过。
- 另外 5 项检查覆盖待机、持续交谈超过 7 秒、Interact、恢复交谈及停止回待机；检查到骨骼运动，人物根节点位移为 0。
- 结果：`quaternius-animation-smoke.json`；画面：`quaternius-idle-a.png`、`quaternius-talking-a.png`、`quaternius-talking-b.png`、`quaternius-interact-a.png`。
- 本轮验证没有调用百炼或其他云服务，没有修改用户知识库、密钥和讲解缓存。当前模型上的动作姿态已检查，其他人物的体型适配与现场全息仓表现仍需实际预览确认。

## 来源与维护

官方来源：https://quaternius.itch.io/universal-animation-library 。Standard 版，CC0 1.0，许可和下载校验信息在 `licenses/Quaternius`。原始下载包保留于 `_downloads/Quaternius`。

`QuaterniusActions.cs` 在构建时导入并校验人形动作，生成 `QuaterniusCatalog.json` 和 Animator 状态；`KioskAvatar.cs` 负责状态驱动、动作预览及恢复；`KioskAdmin.cs` 提供原生预览界面。

正常构建：`tools/Build-Windows.ps1`。输出 `unity/Builds/Windows-Quaternius`；`tools/Package.ps1` 输出新版交付目录。本次服务端代码未改，交付复用已有冻结服务程序。

隔离验证可对新 EXE 传入 `-kiosk-smoke -kiosk-animation-smoke -animation-output <绝对输出目录>`，不连接本地服务、不开启麦克风、不调用云服务，完成后自动退出。
