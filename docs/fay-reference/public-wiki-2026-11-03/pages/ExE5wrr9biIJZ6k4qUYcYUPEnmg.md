# 大语言模型

来源：https://qqk9ntwbcit.feishu.cn/wiki/ExE5wrr9biIJZ6k4qUYcYUPEnmg

给fay搭建本地llm



•
课程ID：fay-lmstudio-course

•
作者：郭泽斌

•
版本：1.0.0

•
章节数：9

•
课程制作工具：https://player.fay-agent.com/

•
课程包:

fay-lmstudio-course.zip
2.46MB

目录

1.
背景

2.
安装lm studio

3.
下载大语言模型

4.
下载embedding模型

5.
加载模型

6.
开启内网通讯

7.
关闭模型的Thinking模式

8.
在fay上完成配置

9.
远程访问模型

第1节 背景

[图片，未 OCR]

讲稿

今天我们演示如何给fay配置本地大语言模型。在人人养虾的今年，线上模型严重超负荷，远远慢于数字人正常对话的要求（五十 token 每秒以上），故咱们需要一个本地的对话模型。如果你有一张3060以上的显卡，请跟着我一步步来搭建这个本地模型，并完成与fay的对接。以windows系统为样板，准备好了的话，咱们就开始吧。

第2节 安装lm studio

[图片，未 OCR]

讲稿

首先，咱们到lm studio的官网下载一个安装包并完成安装。

代码/文案

代码块
Plain Text
复制
https://lmstudio.ai

第3节 下载大语言模型

[图片，未 OCR]

讲稿

在lm studio应用中搜索qwen 3.5 9b并点击下载，等待下载完成。如果你的电脑配置并不高可以选择qwen 3.5 4b。

第4节 下载embedding模型

[图片，未 OCR]

讲稿

以同样的方式下载qwen 3 embedding模型。等待下载完成。

第5节 加载模型

[图片，未 OCR]

讲稿

两个模型都下载完成后，进行开发者栏目（左侧第2个），通过“load model”按钮，分别加载刚才下载的两个模型。此时记得选择弹窗下方的“允许多模型加载”。

第6节 开启内网通讯

[图片，未 OCR]

讲稿

在"server setting"这里打开“serve on local network”，便可以在内网上实现模型请求了。

第7节 关闭模型的Thinking模式

[图片，未 OCR]

讲稿

选中qwen 3.5 9b 模型，在右侧的inference栏中关闭模式，便可以在模型输出阶段关闭思考内容，以更快获得回复。

第8节 在fay上完成配置

[图片，未 OCR]

讲稿

在fay的源码目录找到system.conf文件，如果没有可以把system.conf.bak重命名过来，并配置图中的四项。如果你没有在lm studio上设定key，请随意填写。若你使用的是fay release版，可在安装过程中依引导完成这四项的配置。

第9节 远程访问模型

讲稿

若你和我一样，算力主机在异地，又没有ip专线网络，可以到ngrok.cc购买穿透服务，把lm studio服务端口映射到互联网。

代码/文案

代码块
Plain Text
复制
https://ngrok.cc


