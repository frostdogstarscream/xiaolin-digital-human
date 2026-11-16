# OpenCode Go：MiMo / Qwen Flash 流式延迟测试

测试日期：2026-11-04（北京时间）。本轮 Qwen3.8 Flash 的 low 配置整体快于 MiMo-V2.6-Flash 的 low 配置；Qwen 改用 `reasoning_effort=none` 后，首个正文进一步缩短。

## 实测结果

以下耗时从本机发起 HTTP 请求开始，均为中位数。范围是首个正文的最小值至最大值，包含网络和上游排队，不代表模型纯推理时间。

| 模型与参数 | 成功样本 | 首个正文 | 首句结束标点到达 | 全文接收完毕 | 首个正文范围 |
|---|---:|---:|---:|---:|---:|
| MiMo-V2.6-Flash，`reasoning_effort=low` | 5/5 | 9.72 秒 | 10.26 秒 | 10.88 秒 | 2.42–20.65 秒 |
| Qwen3.8 Flash，`reasoning_effort=low` | 5/5 | 6.89 秒 | 7.04 秒 | 7.21 秒 | 3.90–8.02 秒 |
| Qwen3.8 Flash，`reasoning_effort=none` | 3/3 | 1.61 秒 | 1.86 秒 | 2.32 秒 | 1.24–2.51 秒 |

“首个正文”排除 reasoning 字段；“首句”是正文第一次出现句号、问号、感叹号或分号的时刻，不是实际语音开始时间。报告 JSON 还保留逐块正文时间、20 字到达时间和近似首段缓冲时间。后者只是本地模拟，未执行 Fay 的完整分段处理器。

## 相同问题的首个正文耗时

| 问题 | MiMo low | Qwen low | Qwen none |
|---|---:|---:|---:|
| 你好，小霖，请介绍一下你自己。 | 9.72 秒 | 7.38 秒 | 2.51 秒 |
| 参观时应该注意哪些基本礼仪？ | 15.94 秒 | 8.02 秒 | 1.61 秒 |
| 我只有十分钟，应该怎样安排参观？ | 20.65 秒 | 6.89 秒 | 1.24 秒 |
| 我有点听不清，你能用简单的话解释什么是数字人吗？ | 2.42 秒 | 3.90 秒 | 未测 |
| 谢谢你的讲解，我准备离开了。 | 3.54 秒 | 4.35 秒 | 未测 |

## 参数兼容性

- 两款 low 请求都返回了可见思考内容。MiMo 原生文档只有思考开关；Go 接受 low 不证明其后端存在分级 low 推理。
- `Qwen low + enable_thinking=false`：HTTP 400，错误为上游响应不是有效 JSON。
- `Qwen low + thinking.type=disabled`：HTTP 400，同类错误。
- `Qwen reasoning_effort=none`：3 次 HTTP 200，完整 SSE 结束，均未返回可见 reasoning 字段。usage 没有单独报告 reasoning_tokens，因此不能声称测得内部思考 token 精确为零。
- 两次 400 只证明本轮参数组合未通过当前 Go 路由，不证明 Qwen 原生服务不支持关闭思考。

当前 Go 上通过验证的 Qwen 快速请求参数：

```json
{
  "model": "qwen3.8-flash",
  "reasoning_effort": "none",
  "stream": true
}
```

none 与 low 是两个配置，不能同时生效；以上结果分别列出。

## 条件与限制

- 复用已保存的 Go 端点和密钥；请求逐个执行、不并发、不自动重试。15 次总请求中，13 次完整成功、2 次参数兼容测试返回 400。
- low 使用五个相同问题和相同 system prompt；每轮轮换模型顺序。none 在后续追加，使用前三个相同问题，样本数较少，也可能受缓存、时段和路由变化影响。
- system prompt 要求中文讲解员、两句话、40–70 汉字；实际回复约 45–78 字。没有设置 temperature，避免思考模型对该参数的差异。输出 token 上限 1024。
- 这是一轮短问题抽样；不计算 P95，不作为长期稳定性排名。结果不包含 ASR、Fay 上下文/意图判断、云 TTS、口型生成和 WebRTC 播放。
- 未写入对话历史、未调用 TTS、未重启服务、未切换正式模型。完成后 system.conf 哈希与测试前一致，密钥未写入报告。

原始数据：`go-flash-benchmark-20261104T011104Z.json`。复现脚本：`../tests/benchmark_go_flash.py`；首次运行会在参数失败时停止，`--resume <报告路径>` 完成 low 对照并探测另一写法，`--resume <报告路径> --probe-none` 使用剩余次数测试 none；同一报告最多 15 次。

官方参考：[OpenCode Go](https://opencode.ai/v2/docs/console/go/)、[MiMo 思考开关](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/other/deep-thinking)、[MiMo effort 映射说明](https://mimo.mi.com/docs/en-US/api/chat/responses)。
