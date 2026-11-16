# 播报接口(6000)

来源：https://qqk9ntwbcit.feishu.cn/wiki/UuMOwDShOimrSckrgkxcBEhhnXg

想要实现数字人自动播放（如：虚拟教师、虚拟主播、新闻主播、广告机等），需自主搭建自动播放服务器并实现自动播放服务器接口，参考代码：https://github.com/xszyou/Fay/blob/main/test/test_auto_play_server.py。使用时fay需要正确填写并开启自动播放（支持热启动）。

1.
获取下一条消息接口

接口地址

http://127.0.0.1:6000/get_auto_play_item

请求参数

user：用户名，默认“User”

请求示例

代码块
Python
复制
{
    'user':'张三',
}

返回参数

audio：音频url，为空的时候fay会使用文本来合成

text：文本内容，存在audio url的时候不会使用此文本

timestamp：秒为单位的时间戳浮点值

返回示例

代码块
Python
复制
{
    'audio': 'https://fay.com/test.wav',
    'text': '接下来我们说一下怎么实现一个数字人',
     'timestamp': 113434332
}


