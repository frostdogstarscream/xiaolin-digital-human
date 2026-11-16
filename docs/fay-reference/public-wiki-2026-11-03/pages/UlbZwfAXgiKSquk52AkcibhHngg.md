# 升级日志

来源：https://qqk9ntwbcit.feishu.cn/wiki/UlbZwfAXgiKSquk52AkcibhHngg

Fay数字人推荐的免费开源仓库。没有收费项！也没有在任何平台出售！
1.
Fay数字人开源框架（数字人控制器）：https://gitee.com/xszyou/Fay；
2.
fay-ue5（UE建模，3D数字人，可连接Fay使用）：https://github.com/xszyou/fay-ue5；
3.
Fay-android 远程音频连接器：https://github.com/xszyou/fay-android；
4.
 config server: https://github.com/xszyou/fay_config_server
5.
量化交易agent：https://gitee.com/xszyou/easy-deal
6.
办公室助理：https://gitee.com/xszyou/officeecho
7.
教程制作器：https://gitee.com/xszyou/fay-player
8.
live2d网页数字人：https://gitee.com/garveyer/mate-human
9.
智慧文旅数字人体验平台: https://gitee.com/fay-community/scenic-digital
10.
历史教学的数字人: https://github.com/hack-feng/xingyun-history-teacher

升级日志 fay release下载

2026年08月07周

Fay v4.8.1: https://gitee.com/xszyou/Fay

大小模型逻辑重构 + 单模型模式 + 多处优化

核心改动（大小模型重构）：

•
删死代码约 750 行：LangGraph 工作流、本地知识库、ltp_mode、nlp_cemotion、__check_and_clear_chroma_db、QAService Persona/command 分支

•
命名修复：planner -> judge（闲聊判断器）

•
删除 80 字兜底核实和 kb_search 硬编码优先

•
新增单模型模式：未配置 big_model_engine 时同步执行工具循环

•
重写 docs/Prompt设计文档.md

其他改动：

•
配置中心 URL 更换为 124.220.24.49:5500

•
recorder.py 录音非 16kHz 时重采样到 16kHz

•
fay_booter.py 远程音频连接健壮性修复（recv 空字节/异常退出/socket 关闭/心跳批量清理）

•
mcp_service.py 修复（_serialize_mcp_result 递归序列化、add_mcp_server 用 new_id、werkzeug 多线程替代 gevent）

•
remote_audio_key0.py 按键通话自动开关唤醒词

•
打包默认配置加 big_model_*/embedding_* 字段，system.conf.bak 统一 asr_mode

•
新增 packaging/ 打包脚本、fay.spec、samples/、requirements-legacy.txt



2026年05月04周更新

量化交易agent：https://gitee.com/xszyou/easy-deal

1.
新增 open_position 工具：市价开仓（buy / sell），自动 quantize volume 到 broker volume_step 倍数 + 兜底 tick 抓 bid/ask + 自动生成稳定 magic（不传时 time.time()*1000 & 0x7FFFFFFF）+ 失败带 retcode 中文诊断

2.
两个独立 toggle 互不相干：

EASYDEAL_TRADING_WRITE=1 → close_position + modify_position

EASYDEAL_TRADING_WRITE_OPEN=1 → open_position

用户实战最常见诉求是「让 AI 帮我止损但不让它乱开新仓」——必须拆开两个权限

3.
 修「连续调用 modify_position 只成功第一张」

加 _MT5_RETCODE_TO_CN — 45 个常见 retcode 中文映射（10004–10045）

加 _retcode_explain(retcode) — retcode + mt5.last_error() 组合诊断

之前不带 path 调 mt5.initialize() 随机抓一个 MT5，查盘 / 下单都可能落错户

6.
加 _rebind_mt5(new_install_dir) — 切 MT5 install dir 时的 SDK 重绑函数

_backtest_next_steps_from_hint — 根据 preflight hint 提示具体下一步，不再只返「失败」

hint 涵盖两个 toggle 各自的诊断路径

加 magic 字段（跟 magic_number 并列，兼容老消费方）

加 ts 字段（TimeCurrent() unix sec，让消费方知道这份 runtime 写于何时）



2026年04月04周

Fay v4.4.4: https://gitee.com/xszyou/Fay

1.
用户画像分析增加与fay的关系维度；

2.
fay向自身及下游mcp客户端暴露7个记忆操作相关的mcp工具；

3.
记忆流节点增加 tags 字段，retrieve 支持 AND/OR tag 过滤。

量化交易agent：https://gitee.com/xszyou/easy-deal

1.
EA端加入抗风暴 + 自愈：马丁失败退避、对冲两腿分时下单、GUI 重建；

2.
 MCP端：参数源收敛、加入get_klines 行情工具、修复日志读取的编码识别、跨日轮转、ping 单位口径等隐性bug。

智慧文旅数字人体验平台: https://gitee.com/fay-community/scenic-digital

历史教学的数字人: https://github.com/hack-feng/xingyun-history-teacher



2026年04月03周

Fay v4.4.3: https://gitee.com/xszyou/Fay

1.
release包支持升级功能

2.
增加大小模型支持，交互用小模型、执行用大模型、大模型二次校对小模型输出

3.
Fay 的 MCP 体系支持 Resources 协议，课程知识的目录结构自动注入 LLM prompt

4.
OpenAI 兼容接口透传 context_length

5.
增强运行过程的 embedding 的自愈机制

6.
知识库搜索增强：查询端不拆复合词 + 最低分阈值10.0 + 课程级标题匹配分 + embedding混合评分（通过Fay透传，异步建索引不阻塞MCP）

7.
修复反思记忆时的空表报错bug

8.
修复funasr识别句子完成没执行问题

9.
恢复LLM透传接口支持 model=llm 自动使用配置模型

10.
增加mcp服务开机启动功能

11.
去除gui回车发送换行问题

12.
修复日程管理mcp服务

量化交易agent：https://gitee.com/xszyou/easy-deal

1.
修复多个工具bug，打通了 MCP ↔ EA 的热更新闭环

2.
监测信息将从触发llm的信息移入fay的观察记忆，极大降低词元的消耗

教程制作器：https://gitee.com/xszyou/fay-player

1.
正式更名为教程制作器，定位于软件系统的教程制作

2.
修复复制章节到另一个课程的bug

3.
视频导出包、知识库导出包、课程导出包使用课程名

4.
集成xmov星云数字人api

5.
所有课程设置（包括fay服务器、数字人sdk key）持久化到课程，意味着这些信息将由教程制作方提供，学习方拿到课程包即可实现数字人教学

2026年04月12日

Fay v4.4.2:

1.
release包更新；

2.
llm透传补齐对function call的支持；

3.
优化mcp工具透传功能：强制utf-8、多处bug修复;

4.
新增选择消息生成分享图功能；

5.
优化gui窗口markdown格式显示问题；

6.
新增图文全量知识库mcp服务；

7.
fay内置自身知识库；

8.
think标签内容和prestart标签内容一致，剥离数字人驱动接口的推送；

9.
解决大bug：llm请求有可能触发的线程锁。

fay-ue5:

1.
更换成ue5.6工程包及运行包；

easy-deal:

1.
示例策略加入零损保持机制；

2.
支持策略的持续自我改进；

3.
支持fay、claude code、openclaw的agent模式运行；

4.
新增一组mcp工具。

fay-player:

1.
系统逻辑及ui多处优化；

2.
优化mcp知识库工具；

3.
支持课程另存为及章节复制。

2026年04月05日

fay v4.4.1：

1.
release包更新；

2.
解决内置mcp工具在release包不可用的问题；

3.
Ali tts统一为wav格式；

4.
修复流式输出小数点数字被切断问题；

5.
Fay 向下透传的mcp 服务强制为utf-8编码；

6.
修复tts时的换行符处理问题；

7.
修复wav音频非44100采样率不生成视音素问题。



2026年03月25日

fay v4.3.3：

1.
数字人接口增加数字人指定动作、表情等输出；

2.
解释消息存库时间与日志时间不一致问题；

3.
优化对话prompt及规划器prompt；

4.
解决网络请求阻塞问题；

5.
配置中加载system.conf不持久化；

6.
移除访生记忆保存fay的简洁性；

7.
上传live2d模型。

OfficeEcho:

1.
解决数字人长时间运行的资源释放问题。

Fay-Player:

1.
多处逻辑优化。



2026年03月11日

fay v4.3.2：

1.
打出fay release 安装装包；

2.
优化tts前的换行符处理；

3.
修正prompt模版引入逻辑。

OfficeEcho:

1.
增加横竖屏切换功能；

2.
增加画板功能；

3.
优化资源占用问题；

4.
多处小逻辑优化。

Fay-Player:

1.
初版发布。



2026年03月04日

fay v4.3.1：

1.
增加音频缓存功能，降低tts费率；

2.
优化透传接口流式断句逻辑，域名、版本号等不断句；

3.
优化数字人接口流式文本输出顺序；

4.
llm透传功能接入langsmith，配置环境变量后可通过langsmith平台调优prompt；

5.
优化配置中心加载逻辑，重启后人设配置依然保留。

2026年01月30日：

1.
[配置模块]修复配置加载逻辑;

2.
[接口模块]embedding透传接口;

3.
[知识库模块]优化yueshen知识库初始化逻辑；

4.
[知识库模块]更新yueshen知识库默认使用fay透传的embedding模型；

5.
[知识库模块]补充默认知识库目录“新知识库”；

6.
[核心模块]增加embedding维度检查自动修正逻辑;

7.
[核心模块]修正对langsmith依赖，在没有配置langsmith环境变量时不导入相关包。



2026年01月22日：

1.
[记忆模块]把记忆节点明确区分成对话记忆、观察记忆和反思记忆，并兼容文字沟通接口信息；

2.
[技能模块]补充远程音频按键拾取技能；

3.
多个bug及多处逻辑优化。

2026年01月15日：

1.
修复append_to_buffer bug;

2.
文字沟通接口新增透传llm支持；

3.
文字沟通接口支持不回复控制，记录观察信息；

4.
获取消息接口支持不指定username；

5.
fay 对外mcp接口支持多连；

6.
fay启动命令增加参数config_center（python main.py start -config_center xxxx-xxxx-xxxx-xxxxx ）;

7.
修复多个think标签处理逻辑问题。

2026年01月07日：

1.
增加麦克风、扬声器状态接口及gui自动同步机制;

2.
增加支持向其它MCP客户端暴露自带及开启的工具： http://127.0.0.1:8765/sse ；

3.
补充非开启的预启动工具外部调用接口，如调用查询知识库工具；

4.
修复prestart标签过滤的正规表达式;

5.
修复因prestart标签过滤而导致is first标记有可能掉失的问题;

6.
修复ali tts证书问题。

2025年12月31日：

1.
修复不开启MCP工具无法使用预启动工具的bug;

2.
修复llm对工具调用判断时无法处理think标签的bug;

3.
修复mcp server进程管理的bug;

4.
增加聊天界面消息加载分页功能;

5.
优化日程管理mcp;

6.
修优化系统Prompt、规划器Prompt及最终输出Prompt;

7.
补充开发文档`docs/Prompt设计文档.md`。

2025年12月24日：

1.
修复同一用户多消息会话隔离问题；

2.
增加用户知识画像功能，包括：生成、更新、获取、查看、应用到对话中；

3.
解决gui页面加载速度变慢问题；

4.
gui界面可以添加及删除对话用户；

2025年12月17日：

1.
预启动工具执行结果补充key标识；

2.
清除记忆去除torch的依赖；

3.
把设备的三个（服务器、数字人、远程音频）连接状态放到首页logo中间；

4.
美化gui对预启动结果的显示；

5.
mcp 工具支持预启动及llm调用单独开关控制；

6.
预执行结果可以选择保存到记忆；

7.
chat页面使用”主人“替代默认用户标识；

8.
认知不隔离时使用多用户对话上下文 。

2025年12月10日：

1.
mcp工具预启动功能；

2.
更换认知记忆模块的embedding模型；

3.
去掉原知识库逻辑；

4.
上传知识库mcp服务器；

5.
上传window 窗口截图mcp服务器；

6.
聊天窗口支持markdown排版；

7.
聊天窗口支持缩略图展示。

2025年12月03日：

一. 美化think内容的ui效果

1.
每每条带think内容的消息增加展开窗口；

2.
think加载中的效果美。

二. 优化qa（问答对）管理策略

1.
优化采纳及取消采纳的逻辑；

2.
采纳不记录think内容；

3.
相似问题的答案随机选择输出。



2025年11月12日：

1.
接入仿生记忆算法;

2.
优化prompt;

3.
修复若干bug。

2025年10月15日，Fay升级全新的工具调用机制，实现ai ide级的工具调用稳定性。（参考openai codex cli的实现逻辑）: 
MCP模块

1.
工具调用逻辑由ReAct替换为更稳定的workflow;

2.
为mcp服务补充一个编辑功能；

3.
提供logseq mcp服务器，并作为fay的默认配置之一;

4.
工具调用的文本支持了流式输出；

5.
非富了工具调用时的think日志；

6.
优化agent、llm、工具调用的prompt。

7.
可用的mcp工具列表单独维护，不在nlp时更新；

8.
优化日程管理工具；

9.
修复了若干已知bug。



2025年09月17日Fay自然进化：

- 重构会话管理逻辑支持以下链路基于llm输出、mcp执行、qa问答对匹配时，文字或音频输出的单向或双向打断：

- 1、flask_server.api_send()(gui窗口文字发送) <--> flask_server.api_send_v1_chat_completions()（fay对外的openai兼容接口）

- 2、flask_server.api_send(gui窗口文字发送) <--  flask_server.transparent_pass(消息透传接口)

- 3、flask_server.api_send(gui窗口文字发送) <-- flask_server.to_stop_talking(打断接口）

- 4、flask_server.api_send(gui窗口文字发送) <--> 远程音频

- 5、flask_server.api_send(gui窗口文字发送) <-- 唤醒（普通唤醒、前置词唤醒）

- 6、flask_server.api_send(gui窗口文字发送) <-->日程执行

- 7、flask_server.api_send_v1_chat_completions(fay对外的openai兼容接口) <--> flask_server.transparent_pass(消息透传接口)

- 8、flask_server.api_send_v1_chat_completions(fay对外的openai兼容接口) <-- flask_server.to_stop_talking(打断接口）

- 9、flask_server.api_send_v1_chat_completions(fay对外的openai兼容接口) <--> 远程音频

- 10、flask_server.api_send_v1_chat_completions(fay对外的openai兼容接口) <-- 唤醒（普通唤醒、前置词唤醒）

- 11、flask_server.api_send_v1_chat_completions(fay对外的openai兼容接口)  <-->日程执行

- 12、flask_server.transparent_pass(消息透传接口) <-- flask_server.to_stop_talking(打断接口）

- 13、flask_server.transparent_pass(消息透传接口) <--> 远程音频

- 14、flask_server.transparent_pass(消息透传接口) <-- 唤醒（普通唤醒、前置词唤醒）

- 15、flask_server.transparent_pass(消息透传接口) <-->日程执行

- 16、远程音频 <-- 唤醒（普通唤醒、前置词唤醒）

- 17、远程音频 <-->日程执行

2025年08月28日Fay自然进化：

1、恢复文字、唤醒词、意图接口打断功能；

2、新增支持本地mcp工具调用；

3、支持mcp工具独立控制；

4、内置mcp工具箱及日程管理mcp工具；

5、结束fay时主动关闭（断开）mcp服务；

6、优化线程管理逻辑；

7、支持ctrl+c退出fay。

2025年08月05日Fay自然进化：

1.优化认知机制；

2.funasr依赖更新；

3.更换公共配置中心服务器；

4.优化mcp管理；

5.去除单独情绪计算（llm已经支持）；

6.优化think的“请稍等”提醒逻辑；

7.流式推送给数字人接口的文本补充会话id及消息序号。

2025年06月28日Fay自然进化：

1.
内置RAG知识库（请把docx、pptx、txt文件存放到llm/data目录）；

2.
流式回复逻辑优化；

3.
语音交互逻辑优化；

4.
线程安全增强；

5.
数字人驱动接口增加流式输出开始结束标记；

6.
修复因记忆反思而导致的记忆混乱，无法多轮对话问题；

7.
修复mcp工具获取于调用的线程同步问题；

8.
修复funasr依赖版本问题。

2025年05月17日Fay自然进化：

1.
支持mcp sse服务管理及动态功具调用

--对摩搭社区提供的sse对接的mcp工具做过兼容测试

2.
llm模块统一

--严格匹配openai兼容接口范式，包括token计算及流式控制等

--把认知模式作为llm对接的方式，并对认知模型进行了优化升级，可控制各用户聊天认知是否隔离

--使用qwen3-4b作为默认llm，可以平衡速度、角色模拟与MCP工具调用

3.
提供配置管理中心，便于多个fay做配置管理

--当根目录中system.conf或config.json不存在，启动时会自动载入config_uitl.py中指定的配置

--配置中心代码支持多项目管理，单项目也支持多fay对接，源码地址：

4.
多个bug修复

--修复重复反思和重复保存的问题

--修正认知模型的反思和检索算法

--处理pygame报错程序不继续执行问题

--表情不进行tts

--运行时再判断加载qt5

--修复文字交互接口流式输出时不会结束问题

--修复文字交互接口流式输出qa不输出问题

2025年04月03日Fay自然进化：

1.
增加清除记忆功能；

2.
增加克隆性格功能；

3.
增加认知模型（专属的记忆逻辑、反思逻辑）；

4.
修复自动播报bug；

5.
fay_url配置响修正；

6.
修复流式输出前置换行问题；

7.
修复没有用户聊天记录前端反复添加默认用户问题；

8.
更新dockerfile；

9.
重构util.py代码。

推荐阅读：

1.
Fay ai编程指南：Fay ai编程指南

2.Fay认知模型：
记忆模块

2025年02月27日Fay进化：

1、stream_manager.py补充注释；

2、 gevent包版本更新；#146

3、修复booter与core双互引入问题；#148

4、fay gui支持流式显示，包括<think>标签的内容；

5、修复gpt_stream模式时qa回复不合成语音问题；

6、优化流式deepseek，fay gui及tts对think内容的处理。

7、重构了部分fay_core.py交互逻辑代码；

8、优化机器人表情显示逻辑;

9、把数字人驱动接口标识“Unreal”更改成“human”，消除误解。



2025年02月19日更新：

1、ui显示deepseek 思考窗口；

2、提供Fay ai编程工具二开指南：使用ai编程工具来二开

3、修复使用gpt stream时声音重复合成播放的bug;

4、优化<think>标签内容处理逻辑，只在显示上和声音输出上做处理；

5、去除开启自动运行脚本功能，提高linux和mac的兼容性；

6、优化前端自动获取后端接口地址的方式；

7、agent 模式兼容deepseek。
😇
Agent（兼容deepseek）



2025年02月12日更新：

1、修复录音失败时输出问题；

2、修复linux端启动时，因subprocess报错问题；

3、修复获取状态接口报错问题；

4、新增数字人定位、目标设置；

5、新增启动日志提醒；

6、新增支持流式llm及tts；

7、修正agent多个bug；

8、支持deepseek Deepseek



2025第3周《应用场景验证3：垂直领域的agent》

应用场景验证3：垂直领域的agent



2025第2周《应用场景验证2：大屏数字人中的肢体语言识别》

应用场景验证2：大屏数字人中的肢体语言识别

1、增加一组意图接口：唤醒、打招呼、打断；

2、增加一个自启动脚本列表；

3、修复aliyun asr错误后无法继续拾音问题；

4、优化本地拾音逻辑：麦克风启动时间减小、VAD判断时间减小、错误检查机制、拾音音量动态阈值、调整缓冲区大小；

5、补充自动播放时推送数据的检测；

6、更正qa.csv文件默认编码；

7、去掉http请求日志信息。



2025第1周《场景验证1：量化交易无人直播》

应用场景验证1：量化交易无人直播

1、自动播放逻辑优化：交互完停30秒才继续；

2、降低socket心跳频率，可以一定程序节省安卓远程设备的用电量；

3、增加消息透传接口：
文字交互接口（5000）

4、修复底部用户列表样式错误；

5、提高agent日程执行成功率；

6、上传动图数字人demo 
动图数字人

7、ue5商业唇形工程补充打断功能及支持流式

2024年12月18日更新：

Fay(https://github.com/xszyou/Fay)

1、修复UE连接数字人接口不稳定问题；

2、修复运行途中关闭麦克风依然监听问题；

3、增加打招呼接口，
文字交互接口（5000）；

4、智谱清流llm对接，智普清流。

fay-ue5（https://github.com/xszyou/fay-ue5）

1、上传商业唇型版本；

2、使用旧模型新场景新布局；

3、后台播放声音；

4、支持fay打招呼接口调用。

推荐阅读（含专项交流群）：手表助手



2024年12月11日更新：

fay（https://github.com/xszyou/Fay）：

1、qa回复新增在范围内多条匹配随机命中；

2、gpt问答补充当前时间；

3、命中qa的回复，标示为采纳；

4、新增执行python main.py start命令可自启动；

5、优化CLI机制；

6、优化运行成功后的操作提醒；

7、删掉langchain nlp mudule，修复langchain新旧版包兼容问题。



fay-android （https://github.com/xszyou/fay-android）：

1、恢复简洁状态；

2、3mb极简运行；

3、兼容wear os android手表。



2024年12月04日更新：

Fay(https://github.com/xszyou/Fay)更新：

1、消灭langchain警告信息；

2、修复与funasr对接的包兼容性；

3、推送给数字人的消息区分交互和自动播放；

4、上传ReWoo agent测试代码。



2024年11月27日更新：

Fay

1、去除funasr子协议限制；

2、默认声音替换；

3、修复在服务器上聊天记录时间显示问题；

4、修复前端font缺失问题；

5、前端css调整为本地加载；

6、修复因线程问题，导致启动（关闭）失败、tts不合成等问题；

7、用户切换栏新增左右滑动；

8、修复bs4包安装遗漏问题；

9、修复聊天记录不自动换行问题；

10、修复favicon.ico 缺失问题；

11、补充fay与livetalker（2D模型）音频对接livetalking（2d）

2024年11月20日更新：

Fay

1、升级Agent：升级到langgraph react agent逻辑、集成到主分支fay中、基于自动决策工具调用机制、基于日程跟踪的主动沟通、支持外部观测数据传入；

agent使用指引：
😇
Agent

2、 修复因线程同步问题导致的配置文件读写不稳定；

3、聊天采纳功能的bug修复

Fay-android

1、支持连接Fay服务器或主机端；

2、支持本地whisper语音识别；

3、支持与Fay的语音互传；

4、支持与Fay的文字消息收发；

5、长驻后台运行；

6、收发数据量实时显示；

2024年11月13日更新：

Fay

1、接口新增错误处理机制；

2、nlp_gpt代码重构；

3、首页新增服务器麦克风控制；

4、首页新增服务器扬声器控制；

5、优化socket10001映射到websocket连接；

6、新增未启动时也可以在控制台输入exit进行关闭；

7、新增10002数字人接口传入Output参数可设定不合成音频；

8、处理音色接口格式报错问题；

9、取消edge_tts版本限定；

10、优化手动采纳错误处理。

2024年11月06日更新：

Fay

1、qa自动缓存改为手动采纳；

2、socket10001映射到websocket 9001；

3、修复声音沟通接口无法收音问题；

4、修复阿里云不稳定问题；

5、删除意外出的语音合成开关；

6、唤醒、麦克风、扬声器可以启动后开启和关闭。

2024年10月30日更新：

Fay

1、修复服务器ip配置，配置页没替换问题；

2、修复开启状态偶尔没对齐问题；

3、修复关闭时关闭按钮停留在关闭中问题；

4、修复星座读取错误问题；

5、修复刷新重复提醒开启问题；

6、新增是否进行语音合成的选择；

7、文字沟通接口加入“观察描述”；

8、聊天记录时间改为毫秒级；

9、补充数字人和远程音频的连接状态显示；

10、修复备注填写无法保存问题。

2024年10月23日更新：

•
全新ui

•
全面优化websocket逻辑，提高数字人和ui连接的稳定性及资源开销

•
全面优化唤醒逻辑，提供稳定的普通唤醒模式和前置词唤醒模式

•
优化拾音质量，支持多声道麦克风拾音

•
优化自动播放服务器的对接机制，提供稳定和兼容旧版ue工程的对接模式

•
数字人接口输出机器人表情，以适应新fay ui及单片机的数字人表情输出

•
使用更高级的音频时长计算方式，可以更精准控制音频播放完成后的逻辑

•
修复点击关闭按钮会导致程序退出的bug

•
修复没有麦克风的设备开启麦克风会出错的问题

•
为服务器主机地址提供配置项，以方便服务器部署

模块对接：

•
更新免推理单机数字人aibote对接方式：Aibote

行业应用：

•
数字人教师：躬身入局：数字人教师

2024年10月16日更新：

Fay-助理版

1、更正默认配置；

2、去除麦克风选项（使用系统麦克风）；

3、去掉 eyes(为全新在cv架构做准备)；

4、新增文字语音穿透功能（为统一带货版和agent版做好准备。穿透功能就是把输入的文字直接输出到面板、声音及声音沟通接口和数字人接口，把输入语音直接输出到面板、声音及声音沟通接口和数字人接口。）

4、ollama提示词对接；

5、修复Azure无法修改音色问题；

6、修复wsa_server websocket客户端管理的逻辑问题；

7、修复修复wsa_server websocket线程同步问题。

2024年10月09日更新：

Fay-助理版

1、 优化文字沟通接口的流式输出逻辑

-- fay的文字沟通接口，按标点符号切割并通过http stream返回，这样做语音合成时，能够完整处理每个断句的语音情绪。

2、 去掉内置ngrok.cc内网穿透代码

-- ngrok内网穿透可以让普通pc当作服务器使用，让移动端或者智能设备随时与fay通讯。如需继续使用可以外部启动ngrok或者其他穿透客户端，效果是一样的。

3、优化ASR处理速度

-- VAD（语音活动检测）时间由700ms减小到200ms，可以降低fay识别到我们已经说完一句话的时间，从而让fay更快作出响应

4、优化TTS速度

-- azure不使用ssml明显加速，使用azure tts平均时间可以减小700ms以上

-- 修复本地播放完声音再发送音频给数字人的bug，可以让面板播放音频更快让数字人作出响应（虽然不太可能本地播放和数字人播放同时使用）

-- 语音合成之前替换掉“*”，这是大语言模型经常作出的返回，非常影响语音合成的用户体验

5、优化Q&A文件的应用逻辑

-- 文件格式由excel更换成csv，可以更好兼容linux环境

-- 配置上Q&A文件之后会自动缓存大语言模型回复，相同对话的回复时间可以降到1ms以下

-- csv的第3列可以配置执行脚本，可以实现RPA操作或对智能硬件的控制

6、完善是否做语音合成的逻辑

-- 只有在需要发送远程音频或者发送给数字人或者面板播放时才合成音频，避免资源的浪费

7、修正多用户同时与fay聊天时qa日志有可能混乱的问题

8、 修复fay_core.py上的变量（usernmae）错识导致的远程音频传输出错

9、修复pygame init时无扬声器导致出错

10、去掉面板出现了"完成!"、“远程音频设备连接上”、“远程音频输入输出设备已经断开”、“服务已关闭！”等不必要的日志信息

Fay-UE5：

1、5.4工程，更新为流式对接；

--会从fay小段文字接收然后做tts处理，这样可以更快速作出响应。

2024年09月25日更新：

Fay助理版：

1、重写日志系统：适配多用户逻辑下的panel、数字人端、控制台和文件；补充年月日信息。

2、提高代码可读性，整理代码目录区分llm、tts、asr。

3、 修复ui显示的远程音频连接状态不更新问题。

4、 fay对旧版ue兼容性修复。

5、更新metahuman-stream的对接方式：metahuman-stream（2d）

6、修复web模式读取控制台输入出错bug

7、灵聚nlp接口升级支持多用户对接

8、gpt nlp接口prompt部分接入数字人个人信息，并取消个人信息直接命中匹配

9、coze nlp升级到v3接口

2024年09月19日更新：

Fay-助理版:

•
代码重构：标准化了交互代码、提高了可阅读性、删除了多余代码

•
数字人接口：多路并发接入支持、按用户路由支持、提高了反应速度、使用http音频地址、优化连接状态的判断逻辑

•
远程音频接口：多路并发接入支持、按用户路由支持、单向传输支持、提高了速度、优化连接状态的判断逻辑

•
文字沟通接口：多路并发接入支持、按用户路由支持

•
ui接口：多路并发接入支持、按用户路由支持

•
速度提升：azure tts省去音频转换时间；由轮询交互机制更换成直接交互机制；提高了音频读取速度；去掉所有不必要的sleep；阻塞方法都使用单独线程或协程。

•
明确声音输出逻辑：远程音频接口是否回送依据接口参数要求；数字人接口是否推送依据接口是否被连接；本机是否播放依据本机播放声音开关是否打开（播放时会阻塞）。

•
3.12兼容性修复：websocket工具类把协程转换成任务；pyqt5更换版本。

•
asr多路并发支持

•
nlp多路并发支持

•
tts多路并发（本来就）支持

•
修复python远程音频demo变态声音问题

•
修复命中qa的判断逻辑

•
增加控制台退出进程命令exit

•
优化拾音逻辑：只有在展板播放并且没有使用唤醒功能时才会停止拾音

2024年09月11日更新：

Fay-助理版:

1、删除多余文件：datas、ppn；

2、修改readme图片路径；

3、补充注释；

4、删除多余代码；

5、docker文件整理；

6、http验证文件修改；

7、优化音频处理时间；

8、修复数字人接口的音频时长计算。

2024年09月04日更新：

Fay-助理版&带货版&agent版：

1、websocket服务端连接优化；

2、接入gptsovits v3接口。

Fay-UE5：

1、解决插件AZSpeech在5.4SoundWave无法播放问题；

2、支持连接网页端。

2024年08月28日更新：

•
DONE fay 助理版docker支持多系统

•
DONE fay助理版 ui上多用户对话支持（统一用户管理接口）

•
DONE fay助理版 添加http验证

•
DONE fay-android、python-connector统一音频格式wav

•
DONE duix sdk增加音频播放状态检测（工程包已上传）

•
DONE ue azure版5.3支持独立用户多终端与fay对接

•
DONE ue azure版降级到5.3稳定版

•
DONE ue azure版提供最新一键包

•
DONE ue azure版支持打包后配置azure key（飞书）

2024年08月21日更新：

Fay-助理版：

1、增加启动模式选择，可选择web模式；

2、修复用户名不显示问题；

3、增加docker安装方式；

4、修复10001远程音频端口无法重连问题；

metahuman-stream:

1、对齐官方版本更新；

2、优化对接方式。

2024年08月07日更新：

Fay-agent：

1、统一tts输出为wav格式。

Fay-助理版：

1、统一tts输出为wav格式；

2、优化灵聚授权方式；

3、类gpt接口，远程音频兼容多用户模式；

4、替换默认nlp为moonshot。

Fay-带货版：

1、统一tts输出为wav格式；

2、优化灵聚授权方式。

3、替换默认nlp为moonshot。



2024年07月31日更新：

Fay-agent：

1、接入volcano_tts；

2、类gpt接口兼容流式方式；

Fay-助理版：

1、修复启动时配置有误问题；

2、接入coze；

3、接入volcano tts；

4、类gpt接口兼容流式方式；

5、去除非3.12时报错问题。

Fay-带货版：

1、接入coze；

2、接入volcano tts；

3、加入记录生成到excel；

4、加入本地违禁词检查可关闭；

5、修复gpt记录不读取问题；

6、修复缺失包问题。

2024年07月24日更新：

Fay-助理版：

1.
接入SenseVoice；

2.
接入private-gpt；

3.
python3.12兼容性优化。

Unity：

1.
补充与fay对接部分。



2024年07月17日更新：

Fay-agent版：

1.
优化日程设置；

2.
优化日程提醒。

Fay-UE5：

1.
5.4版本发布；

2.
唇形算法升级；

3.
动作优化；

4.
语音合成队列机制。



2024年07月10日更新：

Fay-agent版：

1.
新增接入gptsovits；

2.
修复聊天信息初始化未成功问题;

3.
修复历史记录为空时报错问题。

Fay-助理版：

1.
新增接入gptsovits；

2.
修复gpt代理配置空某些base_url出现报错问题。

Fay-带货版：

1.
新增接入gptsovits；

2.
修复gpt代理配置空某些base_url出现报错问题；

3.
页面UI优化。

metahuman-stream对接Fay：

1.
修复连接不稳定问题。



2024年07月03日更新：

Fay-agent版：

1.
新增阿里云tts对接；

2.
解决tts前面几个字不读的问题；

3.
优化agent调用工具时递归的问题；

4.
优化历史记录读取、存储问题；

5.
增加自定义读取历史记录条数；

6.
优化prompt逻辑；

7.
优化获取结果时，误报错误问题。

Fay-助理版&带货版：

1.
优化授权表存储逻辑；

2.
新增阿里云tts对接；

3.
解决tts前面几个字不读的问题;

4.
优化百度情感分析、灵聚授权问题.

Fay-UE5：

1.废弃HttpGPT插件，更换为FayConnector插件；

2.支持前置词唤醒模式（需要metahuman本身蓝图上打开）。

















🌟





































失败返回 retcode_explain + pre_validation_warnings + hint，AI 下一轮重试就能调整参数，不再用同款不合规 SL/TP 死循环

TradingContext.init 显式传 EASYDEAL_MT5_INSTALL_DIR 里的 terminal64.exe 给 mt5.initialize(path=...)，锁定到指定实例

Attach 后用 _norm_install_dir 归一化路径比对（剥 .exe + 大小写 + 反斜杠），不一致就 shutdown + retry，最多 5 次

加 _maybe_reload_settings() — 每次工具调用前 cheap stat 一次 EASYDEAL_SETTINGS_PATH 的 mtime，变了就重新加载

副作用：monitor.symbols / magicNumbers / commentContains / Excludes 同步到 strategy_instance；mt5.installDir 变了 → mt5.shutdown + 重新 initialize(path=新 .exe) + 重试绑定

_read_log_utf16_or_utf8 — MT5 tester.log 既可能 UTF-16（BOM）也可能 UTF-8，自动嗅探编码（修「日志里全是乱码」）

easydeal_debug_env 加 trading_write_open_enabled 字段

ea_name 从 "GMarket.mq5" 改成 "GMarket"（跟 ex5 / 监控配置 / 排行榜口径统一）

2024年06月26日更新：

Fay-agent版：

1.
新增支持azure tts；

2.
tts配置分离；

3.
去除农业相关工具；

4.
重构langchain应用逻辑；

5.
新增可接入moonshot；

6.
分离知识库工具，使用需自行在工具内配置。

2024年06月19日更新：

Fay-助理版：

1.
修复langchain安装时默认包版本问题；

2.
提供moonshot对接参考。

Fay-带货版：

1.
优化入场欢迎文案；

2.
优化闲时文案；

3.
新增弹幕规范检查；

4.
新增弹幕违规检查；

5.
新增本地违禁词配置；

6.
新增违禁处理方式配置；

7.
新增弹幕格式过滤；

8.
优化请求角色定义

b站弹幕监听：

1.
修复web接口初始化buvid失败的问题；

2.
移除开放平台模型的UID。

2024年06月12日更新：

Fay-UE5：

1.
修复消息窗口消息重叠显示问题；

2.
开放azure api 区域设置。

Fay-助理版&agent版&带货版：

1.
优化远程音频连接和数字人连接显示。

2024年06月05日更新：

Fay-助理版：

1.
增加funasr热词识别

Fay-agent版：

1.
新增面板发送消息工具；

2.
增加funasr热词识别。

Fay-UE5：

1.
通讯优化；

2.
对话框界面优化；

3.
新增退出按钮。

2024年05月29日更新：

Fay-带货版：

1.
优化互动逻辑；

2、优化互动预料；

2024年05月22日更新：

Fay-带货版：

1.
调整gpt代理默认为空。

Fay-agent版：

1.
去除语音输出工具，改为语音输出只受“语音合成”按钮影响。

Fay-助理版：

1.
调整gpt代理默认为空；

2.
去除funasr_wss方法；

3.
rasa 支持llma3并优化接口；

4.
rasa支持通过vllm部署大模型；

5.
支持通过vllm部署的本地模型启动项目；

6.
采用fastchat既可以降低显存，又能提升响应速度，支持主流模型部署；

7.
修复类 GPT调用失败问题；

8.
新增metahuman-stream对接示例 metahuman-stream对接Fay

Fay-UE5：

1.
增加文本输入框（与Fay会同步消息），方便网页端和移动端操作。

2024年05月15日更新：

Fay-带货版：

1.
新增baidu情绪分析秘钥为空时不使用情绪分析；

2.
去除讯飞nlp。

Fay-助理版：

1.
新增baidu情绪分析秘钥为空时不使用情绪分析。

Fay-UE5：

1.
增加语音按钮，方便网页端和移动端操作;

2.
修复ue4男模工程。

2024年05月08日更新：

Fay-agent版：

1.
配置项新增gpt模型配置、gpt代理默认空。

2024年04月29日更新：

Fay-助理版：

1.
增加百度情绪分析错误解析。

Fay-带货版：

1.
增加百度情绪分析错误解析。

UE：

1.
全新模型、支持最新5.3引擎、使用azure全家桶、支持与Fay异地、支持网页推流、支持打包android、ios及pc客户端。

2024年04月22日更新：

Fay-agent版：

1.
优化获取网页内容工具的兼容性问题；

2.
新增gpt代理配置；

3.
优化白屏问题

Fay-助理版：

1.
使用百度情感分析替换讯飞；

2.
优化白屏问题。

3.
利用vllm对大模型进行加速推理，提升响应时间;

4.
修改rasa对接ChatGLM3-6b模型支持，也可以单独接入ChatGLM3-6B，可以让ChatGLM3-6b提供与openai完全一样的接口。

Fay-带货版：

1.
使用百度情感分析替换讯飞；

2.
优化白屏问题。

2024年04月15日更新：

Fay-agent版：

1.
前端禁止开启后修改；

2.
提高funasr的稳定性。

Fay-助理版：

1.
精简nlp模块；

2.
azure声音模型列表载入方式修改；

3.
增加自动重新载入知识库；

4.
提高funasr的稳定性；

5.
前端禁止开启后修改；

6.
增加文字回复也可以声音输出。

Fay-带货版：

1.
nlp模块精简；

2.
azure声音模型列表载入方式修改；

3.
前端禁止开启后修改



2024年04月08日更新：

Fay-agent版：

1.
优化gpt兼容接口（为ue新工程架构准备）。

Fay-助理版：

1.
*支持azure最新情感音频；

2.
优化gpt兼容接口（为ue新工程架构准备）。

Fay-带货版：

1.
*支持azure最新情感音频。



2024年04月01日更新：

Fay-agent版：

1.
增加agent工具：连接本地知识库（pdf）查询、获取网页内容；



Fay-助理版：

1.
去除已暂停使用的代码

2.
 新增langchain连接本地知识库（pdf）查询

Fay-带货版：

1.
去除已暂停使用的代码 ；



2024年03月25日更新：

Fay-agent版：

1.
增加agent工具：python执行器、网页检索器；



bilibili弹幕监听：

1.
修复兼容性问题

2024年03月18日更新：

Fay-带货版：

1.
问答优先级调整.

Fay-助理版：

1.
问答优先级调整

2.
新增接入langchain nlp模块

3.
新增输出问题前必须开启服务提醒

Fay-agent版：

1.
清除情绪计算的内容



2024年03月11日更新：

Fay-ue5：

1.
发布5.3模型.

Fay-agent版：

1.
取消重启重置日程功能；

2.
上传主动发送微信消息tool(未引入)。



2024年03月04日更新：

Fay-助理版：

1.
去除live2d显示，优化白屏问题；

2.
集成funASR最新版本

Fay-agent版：

1.
优化prompt；

2.
去除llm chain逻辑，减少agent与llm chain切换的token浪费；

3.
优化“思考中...”log，方便后续数字人设计更友好的交互逻辑；

4.
集成funASR最新版本。

2024年02月27日更新：

Fay-助理版：

1.
新增通义星辰nlp对接。

2024年02月19日更新：

Fay-Android连接器：

1.
优化通知弹出逻辑。

Fay-agent版：

1.
增加gpt接口节点配置（方便接入镜像站）。

2024年01月29日更新：

Fay-助理版：

1.
更新类GPT接口逻辑；

2.
增强funasr稳定性；

3.
增加唤醒模式开启时打断数字人说话功能。

Fay-agent版：

1.
增强funasr稳定性；

2024年01月22日更新：

Fay-助理版：

1.
增加问答记录txt(方便obs布局)；

2.
更新fastgpt接口；

3.
增强启动控制器稳定性；

4.
前置唤醒词模式优化。

Fay-带货版：

1.
更新fastgpt接口；

2.
增强启动控制器稳定性；

Fay-ue5：

1.
发布新站姿绿幕数字人。

2024年01月15日更新：

Fay-助理版&带货版：

1.
新增前置词唤醒方式；

2.
新增gpt兼容接口

2024年01月08日更新：

Fay-agent版：

1.
远程音频连接状态显示；

2.
执行任务时记录时间；

3.
去除计算tool，防止用于时间计算而出错。

Fay-助理版：

1.
远程音频连接状态显示；

2.
增加唤醒词自定义功能。

Fay-带货版：

1.
远程音频连接状态显示。

Fay-Android连接器：

1.
优化socket管理；

2.
实测7*24不掉线。

xuniren：

1.
本地对接Fay时使用流式输出。

2024年01月01日更新：

Fay-agent版：

1.
openai token计算；

2.
优化ReAct Agent 与 LLM Chain自动切换逻辑；

3.
添加双记忆机制：长时记忆流及短时聊天记忆；

4.
修复record.py asr bug；

5.
提高远程音频（android 连接器）的稳定性；

6.
修复执行时间计算bug；

7.
优化语音输出逻辑。

2023年12月25日更新：

android 连接器代码分离及优化：

（https://github.com/xszyou/fay-android）

1.
增加重连机制；

2.
优化麦克风及蓝牙sco管理机制；

3.
增加麦克风开关及服务器地址管理

Fay-agent版：

1.
实现agent ReAct与LLM chain自动切换逻辑；

2.
聊天窗区分任务消息；

3.
修复删除日程bug；

4.
优化远程音频逻辑；

5.
等待处理引入加载中效果；

6.
优化prompt以解决日程任务递归调用问题；

7.
修复一次性日程清除的bug。

Fay-助理版：

1.
分离android连接器 app；

2.
优化远程音频逻辑；

3.
未回复消息引入加载效果。

Fay-带货版：

1.
分离android连接器 app；

2.
优化远程音频逻辑。

Fay-ue5：

1.
更新girl|_night工程地址；

2023年12月18日更新：

Fay-agent版：

1.
优化promp；

2.
解决删除日程错误；

3.
iotm demo tool整体优化。

Fay-助理版：

1.
优化fastgpt的对接；

2.
优化gpt的对接；

3.
清除chatgpt的逆向对接方式；

4.
清除部分多余代码。

Fay-带货版：

1.
优化fastgpt的对接；

2.
优化gpt的对接；

3.
把代理提取到配置文件。

2023年12月11日更新：

Fay-agent版第一版上线！

Fay-助理版&带货版：

1.
修复gpt接口报name无效问题；

2.
修复fastgpt报错问题。

2023年12月04日更新：

Fay-助理版&带货版：

1.
内置了fastgpt nlp模块，可借助其接入gpt4;

2.
修复唇形异常报错的问题。

2023年11月27日更新：

Fay-助理版：

1.
 提高websocket稳定性；

2.
修复唇形程序路径问题;

3.
增加SQLLITE稳定性。

Fay-带货版：

1.
提高websocket稳定性；

2.
修复唇形程序路径问题。

Fay-ue5（更新UE工程10月版）：

1.
全新模型；

2.
提供VR运行包；

3.
优化唇形；

4.
改进web socket 状态显示逻辑；

5.
降低性能资源消耗。

VR效果（【VR数字人-哔哩哔哩】 https://b23.tv/1W0sJZv）

xuniren：

1.
提高与Fay对接稳定性。

2023年11月20日更新：

Fay-助理版：

1.
唤醒功能修改：更换为字符判断模式；

2.
增加yolo稳定性;

3.
增加SQLLITE稳定性。

页面引用链接：
https://pan.baidu.com/s/1J-W9PZQEMA49wXrWT1wOpA?pwd=kxca
https://qqk9ntwbcit.feishu.cn/wiki/LjUIwcXRmic1LHk5l57cK4NcnBd
https://qqk9ntwbcit.feishu.cn/wiki/FKFywXWaeiBH28k4Q67c3eF7njC
https://qqk9ntwbcit.feishu.cn/wiki/BSW3wSsMdikiHUkiCJYcSp2lnio
https://qqk9ntwbcit.feishu.cn/wiki/WLg5wde5di5ACqkUu6IcD4w7n0e
https://qqk9ntwbcit.feishu.cn/wiki/Ghh9wFpMIiiFxTk8SlQcZLIrnMf
https://qqk9ntwbcit.feishu.cn/wiki/CctgwyAnTiUQGvkuCLxcdrinnIg
https://qqk9ntwbcit.feishu.cn/wiki/LyBkwpBJ5is306kV554cIIskncc
https://qqk9ntwbcit.feishu.cn/wiki/IOKXwADTXikC9AkhPasciBI4n1f
https://qqk9ntwbcit.feishu.cn/wiki/PNKFwVgUKig6fDkMH03cMPiInIb
https://qqk9ntwbcit.feishu.cn/wiki/IDCjwbUJfiAah2kUu4OcRs4Wnyd
https://qqk9ntwbcit.feishu.cn/wiki/COQwwsqJPiiRkjk9yxPczbV9nIg
https://qqk9ntwbcit.feishu.cn/wiki/J2lnwiEYSiKUf3kF6bfcNp2on2q
https://qqk9ntwbcit.feishu.cn/wiki/Ik1kwO9X5iilnGkFwRhcnmtvn3e
https://qqk9ntwbcit.feishu.cn/wiki/ULaywzVRti0HXWkhCzacoSPAnIg
https://qqk9ntwbcit.feishu.cn/wiki/ZyeawRa5ti23Vpke9TOcTAPvnpg
