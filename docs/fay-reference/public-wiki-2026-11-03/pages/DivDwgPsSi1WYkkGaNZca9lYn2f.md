# mac上安装pyaudio失败

来源：https://qqk9ntwbcit.feishu.cn/wiki/DivDwgPsSi1WYkkGaNZca9lYn2f

[图片，未 OCR]

1、安装brew
brew是mac的一个包管理工具，但使用官网的源去安装会非常慢，而且经常出错，可以使用下面命令选择国内的源去安装。若出错，请多试几次。



2、安装portaudio

portaudio是一个pyaudio上的一个依赖库，mac在安装pyaudio前需要先行安装。



brew install portaudio



3、安装pyaudio



页面引用链接：
https://so.csdn.net/so/search?q=pyaudio&spm=1001.2101.3001.7020
