# Prompt调优教程

来源：https://qqk9ntwbcit.feishu.cn/wiki/OAAJwPKR0i3TBhkAFT3cIfVdnhe

使用langsmith调试fay的prompt

•
课程ID：langsmith-course

•
作者：郭泽斌

•
版本：1.0.0

•
章节数：6

•
课程制作工具：https://player.fay-agent.com/

•
课程包:

langsmith-course (1).zip
1.61MB

目录

1.
配置langsmith

2.
创建key

3.
添加环境变量

4.
安装langsmith库

5.
tracking prompt

6.
fay的llm请求

第1节 配置langsmith

图片

[图片，未 OCR]

讲稿

访问网站https://smith.langchain.com/ 并注册登录

代码/文案

代码块
Plain Text
访问网站https://smith.langchain.com/ 并注册登录

第2节 创建key

图片

[图片，未 OCR]

讲稿

登录后点击左下角的Setting，再进入API Keys栏目，再创建一个Key.

第3节 添加环境变量

图片

[图片，未 OCR]

讲稿

在系统上添加如图4个环境变量，这里key就是上一步保存下来的，project自由填写，待会自动创建的。

第4节 安装langsmith库

讲稿

请在启动fay的python环境里执行如下命令安装langsmith库

代码/文案

代码块
Plain Text
复制
pip install langsmith

第5节 tracking prompt

图片

[图片，未 OCR]

讲稿

此时重启命令终端，再重新启动fay，就可以在平台的Tracking栏目监测到向llm发送的每条消息，也可以看到llm返回的消息。

第6节 fay的llm请求

讲稿

耐心观察，可以看到fay向llm的请求有5情况，分别是： 1.langGraph，这类型是存在可用的mcp工具时，会由llm决定是否调用工具； 2.没有可用mcp工具时的聊天，表现为ChatOpenAI； 3.通过fay向下游提供直链的llm服务，表现为ChatOpenAI，与第2点的区别是没有组合人设、记忆等上下文； 4.用户画象分析，表现为ChatOpenAI，每天执行一次； 5.行为反思，表现为ChatOpenAI，每表执行一次。

代码/文案

代码块
Plain Text
复制
耐心观察，可以看到fay向llm的请求有5情况，分别是：
1.langGraph，这类型是存在可用的mcp工具时，会由llm决定是否调用工具；
2.没有可用mcp工具时的聊天，表现为ChatOpenAI；
3.通过fay向下游提供直链的llm服务，表现为ChatOpenAI，与第2点的区别是没有组合人设、记忆等上下文；
4.用户画象分析，表现为ChatOpenAI，每天执行一次；
5.行为反思，表现为ChatOpenAI，每天执行一次。


