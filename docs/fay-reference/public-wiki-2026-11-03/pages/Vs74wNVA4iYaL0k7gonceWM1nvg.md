# think标签处理逻辑

来源：https://qqk9ntwbcit.feishu.cn/wiki/Vs74wNVA4iYaL0k7gonceWM1nvg

•
课程ID：course-fay-think-tag

•
作者：Fay 开源社区

•
版本：1.1.0

•
章节数：6

•
播放及修改：https://player.fay-agent.com/

•
导入课程包：

course-fay-think-tag.zip
6.51MB

封面

[图片，未 OCR]

目录

1.
为什么 Fay 需要处理 think 标签

2.
think 状态机：进入、退出与超时音频

3.
前端 GUI：parseThinkContent 与折叠面板

4.
数字人 10002：text 与 audio 的对称剥离

5.
进入 LLM 与 embedding 前的 think 清洗

6.
数据库归档与全链路总结

第1节 为什么 Fay 需要处理 think 标签

[图片，未 OCR]

欢迎来到 Fay think 标签处理逻辑课程。

近一年发布的推理类大模型，比如 DeepSeek-R1、o1，以及 Fay 自己的工作流规划阶段，都会输出 ... 这种带显式推理过程的格式。Fay 作为一个数字人对话框架，如果不处理 think 标签，会同时在四个地方出问题：

一是语音输出会朗读出冗长的推理过程；二是 GUI 会被一大堆思考过程刷屏；三是把带 think 的整段文本再喂回 LLM 上下文会让 token 成本爆炸；四是写入向量库后，记忆检索的相关度会严重下降。

Fay 的方案是三层处理：核心进程用一个状态机决定是否丢弃 / 是否广播提示音；GUI 渲染时把 think 拆出来折叠展示；最后在喂回 LLM 与向量化前再清洗一遍。

本课程会顺着 fay_core.py、wsa_server.py、index.html、api_embedding_service.py 这几个关键文件，把整个生命周期串起来。

代码块
Plain Text
复制
# 推理模型输出的典型格式
response = """
<think>
用户问的是天气，我需要先确认城市，然后查询 API...
</think>
今天广州 28 度，晴。
"""

# Fay 不能把这段直接：
#   1. 送进 TTS（数字人会念出推理过程）
#   2. 灌入 GUI（屏幕被推理过程刷屏）
#   3. 写回 LLM 上下文（成本爆炸 + 记忆污染）

第2节 think 状态机：进入、退出与超时音频

[图片，未 OCR]

fay_core 在 say 方法里维护一个用户级的 think 状态机。

状态字段是两个字典：think_mode_users 记录每个 uid 是否处于思考模式，think_time_users 记录进入思考的时间戳。

处理逻辑顺序很关键。先判断结束标记：如果当前流式分片里有 ，把状态机置 False，然后只取最后一个  之后的文本作为正式回答。

再判断开始标记：如果分片里有 ，置 True 并记录时间。

如果当前处于思考模式而且没有 ，整段直接 return None，TTS 拿不到任何东西，数字人保持安静。

唯一的例外是超时机制：如果思考已经持续超过 5 秒，fay_core 会把当前 text 改写成「请稍等...」让数字人主动出声安慰用户，这是 think 模式下 TTS 唯一会被触发的场景。

代码块
Plain Text
复制
# core/fay_core.py - say() 中的状态机片段
if "</think>" in text:
    self.think_mode_users[uid] = False
    parts = text.split("</think>")
    text = parts[-1].strip()
    if text == "":
        return None

if "<think>" in text:
    self.think_mode_users[uid] = True
    self.think_time_users[uid] = time.time()

# 思考超时（>5s）的兜底音频
if self.think_mode_users.get(uid, False) == True \
        and time.time() - self.think_time_users[uid] >= 5:
    self.think_time_users[uid] = time.time()
    text = "请稍等..."
elif self.think_mode_users.get(uid, False) == True \
        and "</think>" not in text:
    return None  # 丢弃这一分片，TTS 不触发

第3节 前端 GUI：parseThinkContent 与折叠面板

[图片，未 OCR]

前端 Vue 组件用 parseThinkContent 这个工具函数把消息内容拆成三段。

扫描逻辑很直接：先用正则找出所有完整的 ... 区段提取为 thinkContent，再找 ... 提取为 prestartContent，最后剩下的就是 mainContent 主回复。

三段在模板里走不同分支：mainContent 交给 markdown-it 渲染成富文本；thinkContent 渲染成默认折叠的紫色折叠面板，用户点击才展开；prestartContent 渲染成 MCP 工具调用结果的浅色卡片。

这一步是纯前端的展示拆分，跟 fay_core 状态机互不干扰：fay_core 决定 TTS 要不要发声，GUI 决定要不要把推理过程露出来给用户。两个职责清晰分开。

流式期间如果分片里  还没闭合，parseThinkContent 会暂时把它当成 mainContent，等下一个流式分片把  补齐后再重新切分，避免折叠面板闪烁。

代码块
Plain Text
复制
// gui/templates/index.html - parseThinkContent
parseThinkContent(content) {
  const thinkRegex = /<think>([\s\S]*?)<\/think>/g;
  const prestartRegex = /<prestart[^>]*>([\s\S]*?)<\/prestart>/g;
  let thinkContent = '';
  let prestartContent = '';
  let mainContent = content;

  let m;
  while ((m = thinkRegex.exec(content)) !== null) {
    thinkContent += m[1] + '\n';
  }
  while ((m = prestartRegex.exec(content)) !== null) {
    prestartContent += m[1] + '\n';
  }
  mainContent = mainContent
    .replace(thinkRegex, '')
    .replace(prestartRegex, '')
    .trim();
  return { thinkContent, prestartContent, mainContent };
}

第4节 数字人 10002：text 与 audio 的对称剥离

[图片，未 OCR]

这一节看 think 内容到底有没有泄露给数字人客户端。

10002 是 HumanServer，由 core/wsa_server.py 暴露，所有推往 10002 的 cmd 都带 Username 字段，wsa_server 会按 Username 把消息只发给绑定该用户的客户端，避免多用户串扰。

数字人客户端会收到两类与 think 相关的消息：一类是状态提示，fay_core 在用户进入思考模式时会推 Topic=human、Data.Key=log、Value=「思考中...」的消息，驱动数字人显示思考气泡；另一类是正式回答的 text 与 audio。

这里有一个曾经存在过的 bug 值得展开讲。fay_core.say 的调用顺序是先 __process_text_output 再走 think 状态机，而 __process_text_output 内部调用的 __send_digital_human_message 在过去只剥 prestart 不剥 think。结果就是：text 通道会原样收到带 ... 的文本，audio 通道因为状态机在后面才执行，倒是被 return None 拦住了。一个数字人接口，text 收到 think、audio 没收到 think，形成了不对称的奇怪状态。

修复方式是新增 __remove_think_tags 函数，处理三种流式场景：完整的 ... 直接剥掉、孤立的  取其后的正文、未闭合的 ... 截断该位置之后的内容。然后在 __send_digital_human_message 里先剥 prestart 再剥 think，使两个标签对称处理。

现在 text / audio 双通道对 think 与 prestart 都做了对称剥离，数字人客户端拿到的就是干净的正文了。

代码块
Plain Text
复制
# core/fay_core.py - 修复后的 __send_digital_human_message
def __send_digital_human_message(self, text, username, is_first=False, is_end=False):
    image_urls = re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', text or '')
    # 先剥 prestart
    cleaned_text = self.__remove_prestart_tags(text) if text else ''
    # 再剥 think —— 与 audio 通道对称
    cleaned_text = self.__remove_think_tags(cleaned_text) if cleaned_text else ''
    full_text = self.__remove_emojis(cleaned_text.replace('*', ''))
    # ...
    content = {
        'Topic': 'human',
        'Data': {'Key': 'text', 'Value': full_text, ...},
        'Username': username
    }
    wsa_server.get_instance().add_cmd(content)

# __remove_think_tags - 处理三种流式分片
def __remove_think_tags(self, text):
    if not text:
        return text
    cleaned = re.sub(r'<think[^>]*>[\s\S]*?</think>', '', text, flags=re.I)
    if re.search(r'</think>', cleaned, flags=re.I):
        cleaned = re.split(r'</think>', cleaned, flags=re.I)[-1]
    if re.search(r'<think[^>]*>', cleaned, flags=re.I):
        cleaned = re.split(r'<think[^>]*>', cleaned, flags=re.I)[0]
    return cleaned.strip()

第5节 进入 LLM 与 embedding 前的 think 清洗

[图片，未 OCR]

Fay 在三个内部环节会主动剥离 think 内容。

第一是写入向量记忆。api_embedding_service.py 在调用 embedding API 之前，会用 _remove_think_from_text 把整段文本先洗一遍，确保向量化的是干净的语义内容，避免推理过程的关键词污染检索结果。

第二是把历史对话喂回 LLM。如果上一轮回复带 think，下一轮再带着这段 think 一起送进 LLM，token 消耗会指数上升，而且 LLM 会被自己上一轮的中间推理迷惑。所以构造 messages 数组前会清洗。

第三是 qa.csv 的「采纳」功能。当用户在 GUI 里把某条 fay 回复采纳为标准答案时，content_db 在比对内容、判断是否已采纳时，会用正则临时把 think 剥掉再比对，避免因为 think 文本不一致导致同一条回复被重复采纳。

总体原则可以记住一句话：展示环节可以保留，但传递与存储环节必须清洗。

代码块
Plain Text
复制
# memory/api_embedding_service.py
def get_embedding(self, text):
    cleaned = self._remove_think_from_text(text)
    # ... 调用 embedding API

def _remove_think_from_text(self, text):
    if not text:
        return text
    return re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()

# core/content_db.py - 采纳比对前剥离
def unadopt_message(self, content, username):
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', content)
    # ... 用 cleaned 在 qa.csv 中查找匹配项

第6节 数据库归档与全链路总结

[图片，未 OCR]

最后一节看 think 在数据库里的命运，并把整条链路串起来。

Fay 通过 core/content_db.py 的 add_content 把每条对话写入 memory/fay.db 的 T_Msg 表。注意：写入时是原始 text，不是清洗后的 final_text。也就是说，如果这一轮 LLM 输出包含 ...，数据库里那条记录里同样保留着它。

这是有意为之：T_Msg 既要支撑 GUI 历史回放，也要支撑「采纳」功能。所以保存时不动原文，比对时用正则临时剥掉。

总结整条链路：

第一，上游 LLM 或 Fay 工作流规划器输出带  的文本流； 第二，fay_core 用 think_mode_users 状态机决定要不要丢弃当前分片、要不要弹「思考中...」、要不要朗读「请稍等...」； 第三，GUI 用 parseThinkContent 把 think 拆出折叠展示，同时 10002 收到 log 类型的「思考中...」状态提示； 第四，正式回答推送到 10002 时，text 与 audio 通道都会通过 __remove_think_tags 与 __remove_prestart_tags 做对称剥离 —— 这是 commit 3638c7b 修复后的状态； 第五，流式结束后，full_response_text 原文写入 T_Msg 数据库； 第六，但是！在喂回 LLM、向量化进入记忆、采纳到 qa.csv 时，think 都会被 _remove_think_from_text 干净地剥掉。

一个标签，多处清洗（状态机 / TTS / 数字人 text / 数字人 audio / embedding / LLM 上下文 / qa.csv），一处保留（T_Msg 数据库归档）。这就是 Fay think 标签处理逻辑的全貌。

代码块
Plain Text
复制
# core/content_db.py - T_Msg 写入保留原文
def add_content(self, type, way, content, username='User'):
    conn = sqlite3.connect(get_path('fay.db'))
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO T_Msg (type, way, content, createtime, username) '
        'VALUES (?, ?, ?, ?, ?)',
        (type, way, content, int(time.time()), username)  # content 含 <think>
    )
    conn.commit()
    conn.close()

# 全链路清洗矩阵
# +------------------+----------+
# | 环节             | 处理     |
# +------------------+----------+
# | TTS 音频         | 剥离     |
# | 10002 text 通道  | 剥离 ✅  |
# | 10002 audio 通道 | 剥离 ✅  |
# | GUI 折叠面板     | 拆分展示 |
# | LLM 上下文       | 剥离     |
# | embedding 向量库 | 剥离     |
# | qa.csv 采纳比对  | 剥离     |
# | T_Msg 数据库     | 保留原文 |
# +------------------+----------+


