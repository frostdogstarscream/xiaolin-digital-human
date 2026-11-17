# 小霖 DiT-v2 × Fay 双引擎 & 竖屏字幕前端蓝绿部署套件

本目录用于将 **A/B 双对话引擎（Qwen Realtime ↔ Fay 完整认知引擎）**、**Fay 人设/MCP 免密反代** 与 **`1080×1920` 竖屏沉浸式字幕前端** 无损部署至云端 Tesla T4（`https://36.133.88.94:6444/`），并在零拷贝复用已有 `rife-dit-v2` 33 GiB 缓存的前提下保留一键回滚能力。

## 部署脚本清单

1. [prepare-dit-v2-fay-release.py](prepare-dit-v2-fay-release.py)：从当前正式目录复制基线并注入 `avatar-2d/experiments/qwen-realtime-v2/{fay_bridge.py, capabilities.py, gateway.py, index.html, demo.js, fay-https-shim.js}`，自动生成 50fps `gateway50.py`，通过 `os.link` 零拷贝硬链接已有 `material-cache`，并归档旧版 `realtime-ingress.json`。
2. [start-dit-v2-fay-candidate.py](start-dit-v2-fay-candidate.py)：拉起候选容器 `xiaolin-formal50-dit-v2-fay`（`8775`/`8776` 自动避让当前线上端口），等待 `/api/health` 就绪并同步 Fay 状态。
3. [validate-dit-v2-fay-release.py](validate-dit-v2-fay-release.py)：在候选容器内执行 WebRTC `1080×1920 @ 50fps`、模式 A 字幕、在线切换模式 B（WebRTC 零断流）、切回模式 A 后 Fay 可编辑性与 MCP 在线数保持全流程验收。
4. [activate-dit-v2-fay-release.py](activate-dit-v2-fay-release.py)：更新 Nginx `6444`（挂接 `/fay/`、`/fay/setting`、`/Page3`、`/api/mcp/`、`/fay-ws` 与 `/experiments/50fps/`，保留一键还原备份），经 `nginx -t` 校验后平滑重载，清理已停用裤装容器 `xiaolin-presenter-1` 并更新 `current-runtime.json`。
5. [rollback-dit-v2-fay-release.py](rollback-dit-v2-fay-release.py)：一键恢复上一版 `nginx.conf`、`control-current.sh` 与原正式容器。

详见完整设计说明：[小霖双引擎 Fay 接入与竖屏字幕前端部署](../../../docs/小霖双引擎Fay接入与竖屏字幕前端部署_20261117.md)。
