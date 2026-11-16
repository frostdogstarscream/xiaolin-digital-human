# 硅基流动付费向量 / 重排与 Fay 关联记忆

部署日期：2026-11-04。关联记忆已开启，按用户名隔离。业务知识库尚未接入，本轮没有注册新的业务工具。

## 当前配置

| 项目 | 设置 |
|---|---|
| Embedding | `Pro/BAAI/bge-m3`，1024维 |
| Rerank | `Pro/BAAI/bge-reranker-v2-m3` |
| 基础地址 | `https://api.siliconflow.cn/v1` |
| 认证 | 本机 system.conf 中独立的 Embedding / Rerank Key，不复用 Go 问答或百炼 TTS Key |
| 关联记忆 | `config.json` → `memory.use_bionic_memory=true` |
| 用户隔离 | `memory.isolate_by_user=true` |
| 重排候选上限 | 30条；返回最多8条，候选不足8条时返回实际数量 |
| 故障行为 | Embedding 不生成模拟向量、不切免费模型；失败的后台记忆写入被跳过。Rerank失败使用已有真实向量候选顺序，不切其他模型 |

Pro 模型属于硅基流动付费条目，区别于不带 Pro 前缀的免费版本。官方价格页：<https://siliconflow.cn/pricing>。付费身份不代表延迟保证，本轮单独记录实测结果。

## 实际工作流程

新问题 → 原生记忆候选召回（时间/重要度/真实向量相关性）→ Pro Rerank → 将相关观察、对话、反思记忆加入提示词 → 当前小模型流式回复。需要后台工具时才按原有协同逻辑调度大模型。

对话结束后的重要度评估仍使用主问答模型，现在沿用小模型的思考设置和 Go 会话头；Embedding 后台写入使用独立硅基流动凭据。检索与后台记忆写入分别记录/执行，不会把测试偏好写进正式用户记忆。

旧记忆3条已经本地备份并全部重新向量化。没有只按维度判断是否需要更新，避免旧模型恰好也是1024维但语义空间不同。原始节点正文保持不变。

正常停止 Fay 时会保存记忆。`fay-ue4/Stop-Fay.ps1` 现在先调用原生核心关闭接口，让其保存记忆，再停止已验证身份的自身进程；正常关闭失败时保留进程保护未保存数据。原有每日保存逻辑保留；未改为逐字同步落盘。

## 验证

- 直接接口检查：Pro Embedding HTTP200，3个有效1024维向量；Pro Rerank HTTP200，相关测试文本排名第一。初次请求分别1.200秒、0.146秒。
- 5项本地检索回归通过：按相关性排序、非法索引处理、关闭重排的原排序兼容、严格向量失败传播、拒绝非法向量。
- 8项现有问答/凭据/TTS回归通过。
- 原生 MemoryStream 的真实向量+重排测试通过，使用进程内合成记忆，没有写入正式用户偏好。
- 正式问答原始 trace 显示 `memory_skipped=false`、`bionic_memory_enabled=true`、`rerank_status=ok`。
- 新对话记忆在正常停止时保存，从3条增至4条；重启新进程后正式问答读取到4条并成功重排，证明保存/恢复链路实际有效。
- 当前 Go 大小模型设置与百炼 Cherry 实时TTS仍生效，原展示会话保留，人物/动作/唤醒词/ASR配置没有改动。

### 两次正式问答耗时

| 指标 | 开启后测试 | 重启恢复后测试 |
|---|---:|---:|
| 查询 Embedding | 92.534ms | 107.129ms |
| Pro Rerank | 483.704ms | 469.628ms |
| 整个记忆阶段 | 578.191ms | 580.762ms |
| 小模型入口至首正文 | 2.715秒 | 2.778秒 |
| 提交至界面回答 | 3.403秒 | 3.466秒 |
| 提交至播放回调 | 4.461秒 | 4.476秒 |

这两次只检索3–4条已有记忆，是小样本；不可作为30候选重排的性能保证。没有进行物理麦克风/外放听感验收。当前 memory 开启意味着用户对话可发送到所选付费 Embedding 服务进行向量化，Rerank 接收当前查询及候选记忆文本；未导入业务文档。

## 配置位置与字段

实际凭据只保存在被 Git 忽略的 `fay-ue4/runtime/fay-local/app/system.conf`，以下使用占位符，报告不保存密钥：

```ini
[key]
embedding_api_model = Pro/BAAI/bge-m3
embedding_base_url = https://api.siliconflow.cn/v1
embedding_api_key = <本机独立保存>
embedding_require_real = true
embedding_timeout = 8
rerank_api_model = Pro/BAAI/bge-reranker-v2-m3
rerank_base_url = https://api.siliconflow.cn/v1
rerank_api_key = <本机独立保存>
rerank_enabled = true
rerank_timeout = 8
rerank_candidate_limit = 30
rerank_top_n = 8
```

原生 Embedding 服务缓存初始化参数；更换其模型/地址/密钥后需要重启 Fay。现有8766/models页仍主要管理问答模型，尚未增加 Embedding/Rerank 编辑表单。

## 交付文件

- `siliconflow-memory-activation-2026-11-04.json`：付费模型接口验证与独立凭据启用结果。
- `memory-retrieval-native-validation-2026-11-04.json`：原生记忆排序验证。
- `memory-embedding-migration-2026-11-04.json`：旧记忆迁移及备份目录。
- `associated-memory-enabled-2026-11-04.json`：记忆开关与公开配置。
- `associated-memory-dialogue-validation-2026-11-04.json`、`associated-memory-restart-validation-2026-11-04.json`：正式问答分段计时。
- `memory-persistence-validation-2026-11-04.json`：正常停止后新增节点持久化检查。
- `memory-retrieval-install-2026-11-04.json`：原生代码补丁摘要及哈希；可用 `tools/install_memory_retrieval.py` 复现安装。

旧记忆备份：`avatar-2d/runtime/memory-model-backups/20261104T020707Z/memory/`。历史记录与旧模型向量均保留在本机备份中。
