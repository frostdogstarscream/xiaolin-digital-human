# 小霖 DiT-v2（Sonic 512→256px 双基准 PatchGAN 全下半脸实时引擎）部署说明

## 1. 核心规格与实测指标

- **教师母带**：CVPR-2025 `Sonic`（512×512 全局音频扩散大模型），全量 4.53 分钟均衡音素语料（`6,800` 帧训练 + `574` 帧严格未见验证集）。
- **实时学生模型**：`XiaolinStudent256UNet`（`256×256` 9 通道双基准输入：遮罩实时姿态 + 闭嘴微笑基准 + 颅骨刚性锁定高清真牙基准，融合 Audio-FiLM + PatchGAN 判别器）。
- **重绘范围**：鼻翼下全下半脸（双侧苹果肌 + 法令纹 + 上下唇 + 门牙列 + 下巴颏 V 型下颌轮廓，高斯后置 100% 侧发防溢保护）。
- **精度与体积**：未见验证集 PSNR **`33.72 dB`**（下半脸 L1 `0.01214`，嘴齿 L1 `0.02545`），FP16 模型体积 **`22.98 MB`**。
- **实时吞吐（FP16 `batch=4`）**：RTX 4090 实测 **`860.6 FPS`（`4.65 ms/batch`）**，单张云端 Tesla T4 约 **`241 FPS`**，原生满足 `1080×1920 @ 50 fps` 实时 WebRTC 推流。

---

## 2. 局域网 RTX 4090 独立 50fps 实时体验（端口 18775）

已与原有 25fps MuseTalk（`18774` / `Open-Xiaolin-4090.cmd`）完全隔离共存：

- **一键启动**：直接双击项目根目录 `Open-Xiaolin-4090-DiTv2.cmd`，自动拉起 `Xiaolin-ASR-4090` 与 `Xiaolin-DiTv2-50fps-4090` 计划任务、建立 `127.0.0.1:18775` SSH 隧道并打开浏览器实时语音对话页。
- **按需释放显存**（在 4090 执行）：
  ```powershell
  schtasks /End /TN Xiaolin-DiTv2-50fps-4090
  ```

---

## 3. 云端 Tesla T4（`https://36.133.88.94:6444/`）蓝绿无损上线与一键回滚

本目录已包含完整自包含资产（`xiaolin_dit_student256_full_best.pth`、`rife_flownet.pkl`、`engine50_dit_v2.py`、`render50_dit_v2.py`、`build-rife-dit-v2-cache.py` 等，仅需上传约 35 MB 权重，在空闲 T4 `GPU0` 本地自动生成 50fps 全身缓存，全程零中断正式 `GPU1` 服务）：

1. 运行 `Start-DitV2-94Session.ps1` 建立受控 SSH 会话；
2. 将本目录同步至云端 `/opt/xiaolin/staging/dit-v2/`，依次执行：
   ```bash
   python3 /opt/xiaolin/staging/dit-v2/prepare-dit-v2-release.py
   python3 /opt/xiaolin/staging/dit-v2/start-dit-v2-candidate.py
   python3 /opt/xiaolin/staging/dit-v2/validate-dit-v2-release.py
   python3 /opt/xiaolin/staging/dit-v2/activate-dit-v2-release.py
   ```
3. **一键秒级回滚**（保留全部在线记忆与配置）：
   ```bash
   python3 /opt/xiaolin/staging/dit-v2/rollback-dit-v2-release.py
   ```
