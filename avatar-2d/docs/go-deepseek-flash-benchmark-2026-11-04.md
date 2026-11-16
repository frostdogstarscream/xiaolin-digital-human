# DeepSeek V4.1 Flash：low 与关闭思考测速

日期：2026-11-04（北京时间）。端点为本机已保存的 OpenCode Go Chat Completions，模型 ID 为 `deepseek-v4.1-flash`。

## 结果

15 次请求全部 HTTP 200、正文非空、finish_reason=stop 且收到 SSE [DONE]。每个配置使用与前一轮 MiMo/Qwen 相同的五个中文问题和 system prompt，顺序执行、轮换配置顺序、不自动重试。以下耗时为中位数，包含本机网络与上游等待。

| 配置 | 成功样本 | 首个正文 | 首句结束标点到达 | 全文接收完毕 | 首个正文范围 | 有可见思考输出的样本 |
|---|---:|---:|---:|---:|---:|---:|
| effort=low | 5/5 | 2.89 秒 | 3.02 秒 | 3.10 秒 | 2.52–5.46 秒 | 5/5 |
| effort=none | 5/5 | 0.91 秒 | 1.12 秒 | 1.25 秒 | 0.70–2.09 秒 | 0/5 |
| thinking.type=disabled + effort=low | 5/5 | 0.88 秒 | 1.05 秒 | 1.19 秒 | 0.78–1.05 秒 | 0/5 |

首个正文排除 reasoning 字段；首句是正文第一次出现结束标点，不是 TTS 实际播放时间。本轮不包含 ASR、Fay 上下文/意图处理、TTS、口型和 WebRTC 延迟。

## 用户要求的关闭思考 + low

当前 Go 路由实测接受：

```json
{
  "model": "deepseek-v4.1-flash",
  "stream": true,
  "thinking": {"type": "disabled"},
  "reasoning_effort": "low"
}
```

DeepSeek 官方说明 `thinking.type` 优先控制思考开关。因此该组合实际为关闭思考，low 不再提供低强度推理；不能解释成同时进行低强度思考。关闭思考两种写法的小样本差异不足以证明其中一种本质上更快。

官方依据：[Chat Completions 参数优先级](https://api-docs.deepseek.com/api/create-chat-completion/)。Go 参数兼容性通过上述真实请求另外验证。

## 每题首个正文时间

| 问题 | low | none | disabled + low |
|---|---:|---:|---:|
| 你好，小霖，请介绍一下你自己。 | 5.46 秒 | 0.88 秒 | 0.90 秒 |
| 参观时应该注意哪些基本礼仪？ | 2.52 秒 | 0.70 秒 | 0.78 秒 |
| 我只有十分钟，应该怎样安排参观？ | 2.89 秒 | 0.91 秒 | 0.87 秒 |
| 我有点听不清，你能用简单的话解释什么是数字人吗？ | 2.61 秒 | 2.09 秒 | 0.88 秒 |
| 谢谢你的讲解，我准备离开了。 | 2.98 秒 | 1.28 秒 | 1.05 秒 |

## 与上一轮的参考对比

| 模型与配置 | 样本数 | 首个正文中位数 |
|---|---:|---:|
| DeepSeek V4.1 Flash disabled + low | 5 | 0.88 秒 |
| DeepSeek V4.1 Flash none | 5 | 0.91 秒 |
| Qwen3.8 Flash none（上一轮） | 3 | 1.61 秒 |
| DeepSeek V4.1 Flash low | 5 | 2.89 秒 |
| Qwen3.8 Flash low（上一轮） | 5 | 6.89 秒 |
| MiMo-V2.6-Flash low（上一轮） | 5 | 9.72 秒 |

跨轮次使用相同问题和提示词，但并非同时交错执行，样本数也不同；缓存、路由和时段可能影响结果。仅是当前短问题抽样，不宣称长期最快或计算 P95。没有测试 MiMo 的关闭思考配置。

原始结果：`go-deepseek-flash-benchmark-20261104T011852Z.json`。脚本：`../tests/benchmark_go_deepseek_flash.py`，复用上一轮流式计时器。实际回复约 44–72 字，输出 token 上限 1024。

本轮未修改正式配置或模型、未写 Fay 对话历史、未调用 TTS、未重启服务。报告中保留测试前后 system.conf SHA256，二者相同；密钥未写入报告。
