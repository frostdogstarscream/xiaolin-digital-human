# funasr的fay使用

来源：https://qqk9ntwbcit.feishu.cn/wiki/OixXwvTbeiBr8UkvxMdcC5UtnPg

•
课程ID：fay_funasr

•
作者：课程作者

•
日期：2026-04-15T15:28

•
版本：1.0.0

•
章节数：7

•
播放及修改：https://player.fay-agent.com/

•
导入课程包：

fay-funasr(1).zip
1.03MB

目录

1.
前置条件

2.
安装独立虚拟环境

3.
激活虚拟环境

4.
安装依赖

5.
启动funasr

6.
fay配置funasr

7.
测试效果

第1节 前置条件

[图片，未 OCR]

开始之前，我们确保系统上已经安装好conda 及python环境。并下载好fay代码包，通过终端进入到代码根目录。

第2节 安装独立虚拟环境

[图片，未 OCR]

我们使用conda 新建一个python 3.12的干净虚拟环境。请在终端输入如下命令。并等待完成，期间应该提问是否安装的，输入"y"回车即可。

代码块
Plain Text
conda create -n funasr312 python=3.12

第3节 激活虚拟环境

输入如何命令激活虚拟环境。

代码块
Plain Text
conda activate funasr312

第4节 安装依赖

[图片，未 OCR]

在终端输入如下命令安装依赖。等待安装完成。

代码块
Plain Text
复制
pip install -r .\asr\funasr\requirments.txt

第5节 启动funasr

[图片，未 OCR]

终端中进入funasr目录，并输入如下合令启动。首次启动会自动下载权重文件，等待完成。看到loaded字眼，代表已经成功了。

代码块
Plain Text
复制
python -u ASR_server.py --host "0.0.0.0" --port 10197 --ngpu 0

第6节 fay配置funasr

fay中修改根目录system.conf中asr_mode为funasr，local_asr_ip为127.0.0.1，local_asr_port为10197,重启fay完成配置。这里要注意，使用了本地配置，请确保在system.conf的必要配置必须完整。同时根目录还必须保留config.json文件，否则系统会判断本地配置不完整，将自动使用公共配置。

第7节 测试效果

[图片，未 OCR]

重启fay后，开启麦克风进行测试。
