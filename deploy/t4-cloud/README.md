# 小霖 T4 云部署

目标：`https://36.133.88.94:6443/`。当前版本 `20261110-ports`，单个活动展示会话；GPU 0 运行 FP32 Wav2Lip256、batch 4，FunASR 在 CPU 上运行，GPU 1 预留。现有静态待机与四动作保持原素材。

## 目录与入口

- `/opt/xiaolin/releases/<版本>`：程序与版本内脚本。
- `/opt/xiaolin/current`：活动版本链接。
- `/opt/xiaolin/shared/config`：受限服务配置、内部认证、TURN 密钥与独立访问账号。
- `/opt/xiaolin/shared/data`：本服务器新增的历史、记忆与运行数据。
- `/opt/xiaolin/shared/assets`：校验后的模型、人物与四动作。
- `/opt/xiaolin/deployment`：环境记录、镜像/依赖/文件清单及控制脚本。

```bash
sudo systemctl start xiaolin
sudo systemctl stop xiaolin
sudo systemctl restart xiaolin
sudo systemctl status xiaolin
sudo /opt/xiaolin/deployment/control.sh status
sudo /opt/xiaolin/deployment/control.sh logs
sudo journalctl -u xiaolin --since today
```

服务默认开机启动。停止流程先关闭展示输出，再通过 Fay 的 `stop-live` 保存记忆，最后停止后台容器。避免直接关闭 Fay 容器而跳过保存。

## 首次访问

1. 获取交付的 `xiaolin-root-ca.crt` 与受限的 `web-access.json`。CA 私钥与服务器证书私钥留在服务器。
2. 在 Windows 执行交付的 `Install-XiaolinCA.ps1`，仅导入当前用户受信任根证书；脚本校验证书文件 SHA256。
3. 打开 HTTPS 地址，在浏览器认证窗口填写独立访问账号与密码。已在首台验收电脑安装 CA。
4. 页面自动建立音视频连接；浏览器麦克风经 HTTPS 上传至服务器 CPU FunASR。“小霖小霖”唤醒后继续问答。

2026-11-10 用户确认云平台已放行 TCP/UDP 6025–10999，来源限定部门出口 `120.195.55.128/28`。当前实际使用以下端口；其他网络来源不在已批准的访问范围内：

| 协议 | 端口 | 用途 |
| --- | --- | --- |
| TCP | 6025 | SSH 运维，服务器内转发至 22 |
| TCP | 6443 | HTTPS、WSS、同源 API |
| TCP/UDP | 6478 | STUN/TURN |
| UDP | 10000–10049 | TURN 中继端口 |
| UDP | 10050–10099 | 服务端 ICE 媒体端口 |

Fay 管理、ASR、MCP、展示内部接口均监听 loopback。Nginx 禁止公开 `/api/tts/`，公开手动播报/动作入口仍返回 410。HTTPS Origin 白名单仅加入正式 IP 来源。不要把管理端口或内部 PCM 令牌暴露到公网。

当前部门网络的 UDP 中继五分钟接收约 23.969 fps，有丢包；TCP 中继独立 98 秒短测约 24.969 fps，丢包增量为 0。正式页面保留直连候选，将 TURN 备用通道配置为 TCP；服务端 Coturn 的 UDP/TCP 监听均保留。不得将 TCP 短测描述为五分钟验收。

## 构建与配置

`build_payload.py` 冻结当前 Windows 源码并生成 Linux 部署副本，包含已验证的 PCM 打断修复、cuDNN 工作区设置、跨平台 FFmpeg 和精确 Origin 配置。原有本机/1660 环境保持现状。只迁移经用户授权的 OpenCode Go、百炼 TTS、硅基流动现用凭据，不迁移历史或记忆库。

`prepare_release.py` 解包、校验文件并创建持久目录链接；`build_images.sh` 构建 Python 3.12 的展示/Fay/ASR 三个独立镜像与 Coturn 镜像。Coturn 采用 Debian 4.6.1 软件包构建，原因是官方容器的一层下载持续停滞。实际依赖、镜像 ID 与 SHA256 清单是该版本的复现依据。

GPU 使用 CDI 设备绑定，避免传统 NVIDIA runtime hook 在 systemd daemon-reload 后丢失设备访问。升级驱动后核对 `nvidia-ctk cdi list` 与 `nvidia-cdi-refresh`，再进行 CUDA 实算验证。

配置写入已处理符号链接，模型设置保存继续落在 shared 目录。打卡服务只执行 `print("success", flush=True)` 并返回 success，不连接真实考勤，预启动执行关闭。

## 回退

```bash
sudo /opt/xiaolin/deployment/control.sh rollback <已保留的版本>
```

回退切换 release 与相应本地镜像标签，保留 shared 数据。启动脚本按目标版本的 ports.json 重新生成 TURN 配置，认证密钥保持不变。目标版本必须已有完整程序和镜像；20261109-1605 使用旧端口，不在本次新批准范围内，不能作为已经验证的新入口回退版本。不要删除 shared、模型或历史版本来“清理”回退。

## 验收与复查

交付目录中的 `acceptance-report.md` 为本次实测结果。`render-report.json` 包含固定 PCM 五分钟测试、四动作、GPU 内存和 H.264 编码信息；`live-cloud-20261109.json` 记录真实模型、TTS、ASR、唤醒和 MCP 故障恢复。

`check_https.py` 验证严格证书校验、访问认证、WSS、Origin 拒绝、关闭入口及本机 TURN 分配；它不证明公网中继可用。`check_reconnect.py` 验证两个连续本机 WebRTC 连接及重连不执行打卡。公网验收需在云安全组放行后使用 `browser-observe.js` 和 `browser-force-turn.js` 完成，维持证书严格校验。

真人麦克风、扬声器和完整动态观感保留现场人工验收。本轮没有新增自然待机循环。
