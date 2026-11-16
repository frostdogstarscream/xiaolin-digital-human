# “[!]语音未检测到内容！”如何解决？

来源：https://qqk9ntwbcit.feishu.cn/wiki/GHf9wVeXsiRqXNk9cXtcnpqonmc

在fay控制器运行时，虽然控制台没有报错，但是会出现“[!]语音未检测到内容！”，这个问题该如何解决？

[图片，未 OCR]

首先确保相关的key填写正确



目前遇到出现这个问题的有以下几种情况

1.未关闭系统代理

开了代理会无法连接阿里云，导致出现这种情况，关了代理就好了。

可以在运行fay控制器前，先运行test文件夹下的“clear_proxy.py”关闭系统代理：

[图片，未 OCR]

2.麦克风无法使用

检查麦克风是否能正常使用；

可以使用查一下麦克风的信息，阿里云api仅支持'maxInputChannels'为'1的麦克风。

可以运行test文件夹下的“testpyaudio.py”查询麦克风：

[图片，未 OCR]



3.numpy版本过低可以尝试更新一下numpy的版本。

pip install --upgrade numpy
