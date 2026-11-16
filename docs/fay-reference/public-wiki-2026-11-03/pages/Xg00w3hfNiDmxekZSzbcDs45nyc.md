# 大小模型协同工作逻辑

来源：https://qqk9ntwbcit.feishu.cn/wiki/Xg00w3hfNiDmxekZSzbcDs45nyc

Fay 的大小模型协同工作逻辑

•
课程ID：course-fay-big-small-model-collab

•
作者：Fay 开源社区

•
版本：1.0.0

•
章节数：6

•
播放及修改：https://player.fay-agent.com/

•
导入课程包：

Fay-的大小模型协同工作逻辑 (1).zip
2.06MB

封面

[图片，未 OCR]

目录

1.
为什么 Fay 要搞大小模型协同

2.
模型工厂：按 role 切换大小模型

3.
小模型当第一响应者：闲聊判断与工具分流

4.
大模型后台执行循环：ExecutionManager

5.
任务运行中：新消息的意图分类

6.
后台完成回填：小模型改写结果与全链路总结

第1节 为什么 Fay 要搞大小模型协同

[图片，未 OCR]

欢迎来到 Fay 大小模型协同工作课程。

单模型做数字人对话有一个绕不开的矛盾：想让首句响应又快又便宜，就得用小模型；但小模型在工具规划、长链路推理、事实核查上能力有限，换大模型又会让每一次"你好"都要等三五秒、花一笔不小的 token 费。

Fay 的解法是让两种模型各干各擅长的事：小模型当第一响应者，立刻开口接住用户，判断这是闲聊还是需要查工具；大模型当后台执行者，在独立线程里跑工具调用循环，完成后把结果交还给小模型改写成最终回复。

这套机制在 Fay 里由三块代码支撑：system.conf 里分别配置 gpt_model_* 与 big_model_* 两组模型；llm/nlp_cognitive_stream.py 的 question 函数做分流；llm/execution_manager.py 跑后台执行循环。

本课程会顺着这条链路，把协同机制从入口到回填完整讲一遍。

代码块
Plain Text
复制
# system.conf - 两套模型并存
# 小模型：扛首句响应、闲聊判断
gpt_model_engine = qwen/qwen3-4b-2507
gpt_base_url = https://...
key_gpt_api_key = sk-...

# 大模型：扛后台工具执行循环
big_model_engine = MiniMax-M2.7
big_model_base_url = https://api.minimax.chat/v1
big_model_api_key = sk-cp-...

# 大模型未配置时会自动降级为小模型
# 也就是说：小配置可以单跑，协同是可选增强

第2节 模型工厂：按 role 切换大小模型

[图片，未 OCR]

第二节看一眼 Fay 如何在一份代码里同时拿到大模型和小模型实例。

关键函数在 llm/execution_manager.py 的 _get_llm_instance。它只有一个参数 role，取值 small 或 big，返回一个 ChatOpenAI 对象。

当 role 是 big 时，它优先读 system.conf 里的 big_model_engine、big_model_base_url、big_model_api_key。如果某个 base_url 或 api_key 为空，会回落到小模型的 gpt_base_url、key_gpt_api_key，也就是说你可以只换模型名不换服务商。

关键的一行是：如果 big_model_engine 本身没配，会打印"请求大模型但未配置，降级为小模型"，然后按小模型参数构造。这让 Fay 对单模型用户依旧可用——协同是增强特性而不是硬依赖。

另外一个细节是超时与重试：大模型 timeout 120 秒、max_retries 2；小模型 timeout 60 秒、max_retries 1。这背后的假设是——大模型要跑工具循环、响应时间本来就长；小模型要扛首句响应，失败了宁可快速失败也别让用户干等。

代码块
Plain Text
复制
# llm/execution_manager.py - 模型工厂
def _get_llm_instance(role: str = "small", streaming: bool = True) -> ChatOpenAI:
    cfg.load_config()

    if role == "big":
        if cfg.big_model_engine:
            actual_base_url = cfg.big_model_base_url or cfg.gpt_base_url
            actual_api_key  = cfg.big_model_api_key  or cfg.key_gpt_api_key
            return ChatOpenAI(
                model=cfg.big_model_engine,
                base_url=actual_base_url,
                api_key=actual_api_key,
                streaming=streaming,
                timeout=120, max_retries=2,
            )
        # 无大模型配置 → 降级为小模型
        util.log(1, "请求大模型但未配置 big_model_engine，降级为小模型")

    # small / 降级路径
    return ChatOpenAI(
        model=cfg.gpt_model_engine,
        base_url=cfg.gpt_base_url,
        api_key=cfg.key_gpt_api_key,
        streaming=streaming,
        timeout=60, max_retries=1,
    )

第3节 小模型当第一响应者：闲聊判断与工具分流

[图片，未 OCR]

第三节讲小模型当第一响应者时，它到底在判断什么。

在 question 函数里，如果没有正在执行的后台任务且注册了工具，Fay 会调用 _call_planner_llm 走规划器。规划器的 system prompt 很特别——它不是一个通用助手，而是一个闲聊判断器，只输出两种合法 JSON：是闲聊就 {"action": "finish", "message": "..."}，不是闲聊就 {"action": "tool", "keyword": "..."}。

关键约束写在 prompt 里：小模型被明确告知"你是第一响应者，涉及事实信息的回答系统会在后台另起一个大模型自动核实"。所以它被禁止在 message 里写"我来查一下""稍等我核实"这种过渡语——过渡语由系统统一插入，小模型写了只会和系统重复。

流式阶段还有一个设计：规划器边流边解析。只要早期 token 能判定是 tool 分支，立刻触发 on_tool_detected 回调，先推一句"我来帮你查一下，稍等…"给用户，然后把工具调用提交给大模型后台。这一下把"大模型开始干活"的感知延迟几乎压到零。

还有一个兜底：如果小模型把 finish 写得超过 80 字，Fay 会认为它在硬编事实信息，自动追加"等等，我再帮你核实一下…"并把请求转交给大模型。

代码块
Plain Text
复制
# llm/nlp_cognitive_stream.py - 规划器分流（节选）
first_decision = _call_planner_llm(
    plan_state,
    stream_callback=_first_plan_stream_callback,  # finish 边流边出
    on_tool_detected=_on_tool_detected,            # tool 时提前插过渡语
)

if first_decision["action"] == "tool":
    # kb_search 场景：硬塞首工具给大模型
    return _submit_tool_execution(
        {"tool": "kb_search", "args": {"query": search_query}},
        show_plan_msg=not already_notified,
    )

# finish 分支的越界兜底：finish 过长 → 自动转核实
finish_msg = first_decision.get("message", "")
if has_tools and len(finish_msg) > 80 and len(content.strip()) > 3:
    write_sentence("\n\n等等，我再帮你核实一下…\n\n---\n")
    return _submit_tool_execution(
        {"tool": None, "args": {}},
        show_plan_msg=False,
        unverified_response=finish_msg,  # 带上小模型原回复，供大模型对照
    )

第4节 大模型后台执行循环：ExecutionManager

[图片，未 OCR]

第四节看大模型在后台到底怎么跑。

llm/execution_manager.py 定义了一个 ExecutionManager 单例，内部维护两张字典：_states 存每个用户当前的 ExecutionState，_threads 存对应的后台线程。submit 方法会先检查同一用户是否已有运行中的任务，如果有就直接返回 False——也就是说每个用户同时只有一个大模型线程，防止并发工具冲突。

核心循环是 _big_model_execute。流程是这样的：如果小模型在规划阶段硬塞了首工具（比如 kb_search），就以它作为起点；否则让大模型自己规划首步。然后进入最多 30 步的执行循环——调用工具、记录结果、把整个已执行摘要塞给大模型让它决策下一步，要么继续 tool，要么 finish。

这里有两个值得注意的防御机制。第一是防重复调用：每次大模型返回一个新 tool 决策，先扫整段 tool_results，如果已经有同名同参且成功的调用，就直接终止循环——避免模型在上下文压缩后重新发一遍同样的工具。第二是 cancel_flag 与 modify_request：用户在任务执行期间想插话的话，可以通过管理器传进来，循环每一轮都会检查一次。

循环结束后，所有工具结果会被拼成 final_tool_context 字符串，再加上大模型最后给出的 final_response_hint，一并等小模型来消费。

代码块
Plain Text
复制
# llm/execution_manager.py - 后台执行循环（节选）
def _big_model_execute(state: ExecutionState):
    big_llm = _get_llm_instance("big", streaming=False)
    current_action = state.first_plan  # 可能由小模型预先指定
    max_steps = 30

    while len(state.tool_results) < max_steps:
        if state.cancel_flag: return                       # 用户取消
        if state.modify_request:                           # 用户补充要求
            state.audit_log.append(f"收到修改指令: {state.modify_request}")
            state.modify_request = None

        spec = state.tool_registry.get(current_action["name"])
        success, output, error = spec.executor(current_action["args"], attempts)
        state.tool_results.append({"call": current_action, "success": success, ...})

        # 大模型决策下一步
        decision = _extract_decision(big_llm.invoke(_build_execution_next_step_messages(state)))

        if decision["action"] == "tool":
            # 防重复：同名同参已成功 → 直接终止
            if any(r["success"] and r["call"] == decision_call for r in state.tool_results):
                break
            current_action = {"name": decision["tool"], "args": decision["args"]}
        else:  # finish
            state.final_response_hint = decision.get("message", "")
            break

第5节 任务运行中：新消息的意图分类

[图片，未 OCR]

第五节看一个协同框架绕不开的难题：后台任务还在跑，用户又发了一条新消息，该怎么处理。

Fay 的答案在 question 函数的"情况2"分支。当检测到用户有 RUNNING 状态的 ExecutionState 时，会用小模型跑一次轻量级意图分类，输出五个标签之一。

update_task 表示用户在补充当前任务的要求——比如原来问天气，补一句"只要今天的"，这时候调用 exec_mgr.modify 把指令塞给正在跑的大模型循环，大模型下一轮决策会看到这条补充。

query_progress 表示用户在问进度——"好了没""还要多久"，系统直接从 state.current_step 和 tool_results 长度读出当前进度报出来，不打扰大模型。

cancel_task 就是放弃任务，直接把 cancel_flag 置 True，大模型循环在下一轮检查时退出。

new_task 最微妙——系统判断用户提的是一个独立新任务。这时候不会粗暴打断，而是生成一句反问："我正在帮你处理 X，你是想加这个新需求还是改做新的？"交给用户确认。

normal_chat 是和任务无关的闲聊，小模型直接用 run_direct_llm 回复一句，后台任务继续跑不受影响。

这套分流让"协同"不只是两个模型轮流跑，而是在用户看来对话始终流畅。

代码块
Plain Text
复制
# llm/nlp_cognitive_stream.py - question() 情况2（节选）
running_state = exec_mgr.get_state(username)
if running_state and running_state.status == ExecutionStatus.RUNNING:
    intent = _classify_intent_for_running_task(content, running_state)

    if intent == "update_task":
        exec_mgr.modify(username, content)            # 补充要求塞入大模型循环
        reply = "好的，我已经把你的补充要求传达给正在执行的任务了。"
    elif intent == "query_progress":
        reply = (f"正在执行：「{running_state.original_request}」\n"
                 f"当前进度：{running_state.current_step}，"
                 f"已完成 {len(running_state.tool_results)} 步。")
    elif intent == "cancel_task":
        exec_mgr.cancel(username)                      # 置 cancel_flag
        reply = "好的，已取消正在执行的任务。"
    elif intent == "new_task":
        reply = _build_new_task_confirm_reply(content, running_state)  # 反问确认
    else:  # normal_chat
        run_direct_llm()                               # 小模型直接回复，不打扰后台

第6节 后台完成回填：小模型改写结果与全链路总结

[图片，未 OCR]

最后一节看大模型跑完后结果怎么回到用户眼前，并把整条协同链路串起来。

大模型后台线程执行完毕时，ExecutionManager 会触发 on_complete 回调——也就是 _auto_reply_after_execution。这个函数的目标是：不重新进入 question 全流程（避免重新加载记忆与历史导致上下文溢出），用一个精简 prompt 让小模型基于工具结果生成最终回复，并写回原始 conversation_id 的流。

精简 prompt 里只保留三样东西：用户原始请求、工具调用细节、工具执行结果。系统明确告诉小模型"你已经说过'我来帮你查一下，稍等…'，不要再重复过渡语，直接给答案"。小模型流式输出，按标点切句写入 stream_manager。

一个很有意思的细节：Fay 会把大模型的完整执行日志包在 … 里作为最终消息的前缀，GUI 会把它折叠成"思考过程"面板。用户既看到干净的答案，也能点开看大模型到底调了哪些工具、耗时多少。

如果这是一次核实场景（兜底分支传入了 unverified_response），小模型的 prompt 还多一条规则：比对工具结果和之前的未核实回复——一致就说"核实了一下，刚才说的没问题"；有矛盾才更正。避免为了"显得勤快"去修改其实正确的回答。

整条协同链路串一下： 第一，用户消息进 question，小模型规划器边流边判断，闲聊直接流出，非闲聊推过渡语并提交大模型。 第二，ExecutionManager 在独立线程里跑大模型循环，防重复、可取消、可修改、最多 30 步。 第三，循环期间用户的新消息由小模型做意图分类，根据 update/query/cancel/new/normal 五种分支分别处理。 第四，循环结束，_auto_reply_after_execution 用精简 prompt 让小模型改写成最终回复，附执行日志 。 第五，回复进入同一 conversation_id 的流，记忆存入对话历史，状态清空，等待下一轮。

一份小模型配置 + 一份大模型配置 + 一个执行管理器 = Fay 在数字人场景下的低延迟、高质量对话。这就是 Fay 大小模型协同的全貌。

代码块
Plain Text
复制
# llm/nlp_cognitive_stream.py - _auto_reply_after_execution（节选）
def _auto_reply_after_execution(username, finished_exec_state):
    sm = stream_manager.new_instance()
    conv_id = finished_exec_state.conversation_id
    sm.set_current_conversation(username, conv_id)   # 复用原会话

    tool_context = finished_exec_state.final_tool_context[:4000]
    hint         = finished_exec_state.final_response_hint[:500]

    compact_system = f"""你已经告诉用户"我来帮你查一下，稍等…"，现在工具执行完毕。
请基于工具结果直接回答，不要再重复过渡语。
**用户消息**: {finished_exec_state.original_request}
**工具执行结果**:
{tool_context}
"""

    small_llm = _get_llm_instance("small", streaming=True)

    # 把大模型执行日志作为 <think> 前缀写回
    think_tag = f"<think>\n执行耗时: {elapsed}s，共 {len(tool_results)} 步\n...\n</think>\n"
    _write(think_tag, force_first=True)

    for chunk in small_llm.stream([SystemMessage(content=compact_system), HumanMessage(...)]):
        # 按标点切句，流式写回同一 conversation_id
        ...

    exec_mgr.consume_result(username)                # 清理状态
    MyThread(target=remember_conversation_thread,
             args=(username, original_request, full_text)).start()  # 记忆归档

# 全链路协同矩阵
# +-------+----------+--------------+------------------+
# | 阶段  | 角色     | 模型         | 关键产出          |
# +-------+----------+--------------+------------------+
# | 入口  | 规划器   | 小模型       | finish / tool    |
# | 执行  | 执行者   | 大模型       | tool_results     |
# | 插话  | 分类器   | 小模型       | intent 标签       |
# | 回填  | 改写器   | 小模型       | 最终流式回复       |
# +-------+----------+--------------+------------------+


