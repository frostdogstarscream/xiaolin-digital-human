# 本地通信协议

服务绑定 `127.0.0.1`：主服务端口 `8765`，独立演示接口端口 `8766`。Unity 客户端用 HTTP 管理、WebSocket 交互；不依赖浏览器。服务拒绝携带网页 Origin 的控制请求，默认不向局域网开放。

## HTTP 管理

| 路径 | 方法 | 用途 |
|---|---|---|
| `/health` | GET | 服务标识、版本、密钥是否配置；不代表上游授权成功 |
| `/api/settings` | GET / PUT | 角色、显示、音频和 AI 模型配置；保存时终止旧回答并重置历史 |
| `/api/credentials` | POST | 本地管理台保存百炼密钥；请求字段 `api_key`，响应不回传密钥 |
| `/api/chapters` | GET / PUT | 三个主题及句子数组 |
| `/api/documents` | GET / POST | 资料列表；上传为 multipart `file` 和 `knowledge_base` |
| `/api/documents/{id}` | DELETE | 删除原文与索引 |
| `/api/knowledge/index` | POST | 启动向量索引任务 |
| `/api/cache/prepare` | POST | 启动全部角色欢迎语和讲解缓存生成 |
| `/api/cache` | GET | 各角色、章节已缓存句数 |
| `/api/jobs` | GET | 后台索引、缓存任务状态 |
| `/api/events` | GET | 最近运行记录，最多持久保留 2000 条 |

密钥只由本地服务读取；不要通过非本机网络暴露管理接口。日志保留问题、答案、引用和工具回执，可能包含导入的业务信息；不保存原始录音和密钥。

## WebSocket `/ws`

所有服务事件包含 `type`、`session_id`、递增的 `turn_id`。客户端仅接受当前会话且不早于当前轮次的内容。音频还包含 `segment_id`；停止时清空声音、嘴型和待播队列。新连接取代旧交互会话。

客户端 JSON 指令示例：

```json
{"type":"text","text":"切换到业务流程"}
{"type":"narration","action":"start","chapter_id":"overview"}
{"type":"narration","action":"pause"}
{"type":"narration","action":"resume"}
{"type":"greet"}
{"type":"interrupt"}
{"type":"audio.start","mode":"push_to_talk"}
{"type":"audio.end"}
{"type":"playback.complete","turn_id":4,"segment_id":"服务返回的片段标识"}
```

录音开始后等待 `capture.ready`，再发送 WebSocket 二进制帧：16 kHz、16 位有符号小端、单声道 PCM。服务返回 `transcript.partial`、`transcript`、`sources`、`answer`、`tool.result` 和 `state`。

播报为 `speech.begin` → 多个 `audio` → `speech.end`。`audio.pcm` 为 base64 PCM（24 kHz、16 位小端、单声道）。客户端实际播放完成才发 `playback.complete`；下载完成不能推进讲解句子。`playback.stop` 使旧片段失效；旧确认不会改变新讲解位置。

## 演示业务接口

```text
POST http://127.0.0.1:8766/scene/switch
{"scene_id":"workflow"}

GET http://127.0.0.1:8766/scene/status
```

主题白名单：`overview`、`workflow`、`value`。状态持久保存，回执标记 `simulation: true`。LLM 可使用 `switch_scene`、`get_scene_status`，以及经过校验的讲解控制工具；没有执行任意 shell 或任意 URL 的工具。

接入真实平台时在 `service/business.py` 扩展适配层，保留参数白名单、超时限制、成功回执验证和失败直达用户的路径。写操作超时表示结果未确认，不自动重试，不播报成功。
