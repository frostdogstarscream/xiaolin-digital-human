# 意图接口(5000)

来源：https://qqk9ntwbcit.feishu.cn/wiki/ZmIAwppguiL2GJk4WX6cYhxgnPh

1.
打招呼接口

接口地址

http://127.0.0.1:5000/to-greet

参数

username：用户名

observation：同上

请求示例

代码块
Python
复制
{
    "username":"User",
    "observation":{"address":"车陂街道","人脸识别":"张三（主人的朋友）"}
}

返回：

代码块
Python
复制
{
    "data": "你好！我是菲菲，随时为你服务！",
    "msg": "已进行打招呼",
    "status": "success"
}



2.
唤醒接口

接口地址

http://127.0.0.1:5000/to-wake

参数

username：用户名

请求示例

代码块
Python
复制
{
    "username":"User"
}

返回：

代码块
Python
复制
{
    "msg": "已唤醒",
    "status": "success"
}



3.
打断接口

接口地址

http://127.0.0.1:5000/to-stop-talking

参数

username：用户名

observation：同上

请求示例

代码块
Python
复制
{
    "username":"User",
    "observation":{}
}

返回：

代码块
Python
复制
{
    "msg": "已停止说话",
    "status": "success"
}



4.
消息透传接口

接口地址

http://127.0.0.1:5000/transparent-pass

参数

user:非必，用户名

text:必须，透传的消息内容

audio:非必，透传的音频（存在音频时不对text tts）

请求示例

代码块
Python
复制
{
    "user":"User",
    "text":"你好，请说？",
    "audio":"https://xxx.com/aaaa.wav"
}

返回：

代码块
Python
复制
{
    "code": 500,
    "message": "成功"
}


