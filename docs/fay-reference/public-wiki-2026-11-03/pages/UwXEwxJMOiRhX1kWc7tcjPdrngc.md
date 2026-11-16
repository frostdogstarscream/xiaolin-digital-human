# 数字人驱动接口（10002）

来源：https://qqk9ntwbcit.feishu.cn/wiki/UwXEwxJMOiRhX1kWc7tcjPdrngc

目的：数字人皮肤对接fay的接口，可以对接2d、ue、unity等皮肤。



通讯地址

ws://127.0.0.1:10002

注：fay作为服务端

消息格式

通讯地址: ws://127.0.0.1:10002

注：ue作为客户端

1.  fay向数字人发送音频

代码块
JSON
复制
{"Topic": "human","Data": {"Key": "audio","Value": "c:/fay/sample/audio/sample-1.wav","HttpValue": "http://192.168.1.13:5000/audio/sample-1.wav","Text" : "很高兴见到你","Lips":[{"Lip": "sil", "Time": 180}, {"Lip": "FF", "Time": 144}],"Time": 10,"Type": "interact", "IsFirst":1, "IsEnd":0,"Sentiment": 0.7,
    "Action": {
      "code": "guidance.invite",
      "behavior": "invite",
      "affect": "warm",
      "intensity": 0.74,
      "priority": 82
    }}}

唇形（只支持windows）的定义：

唇型定义.docx



关键词及动作、表情对应表：

关键词或意图示例	code	behavior	affect	intensity	priority
你好、您好、hello、hi	greeting.hello	nod	smile	0.35	60
欢迎、欢迎光临、欢迎来到	greeting.welcome	invite	warm	0.78	80
再见、拜拜、goodbye	farewell.goodbye	wave	smile	0.62	72
是的、没错、收到、明白	dialogue.confirm	nod	smile	0.42	58
不是、不行、不能、no	dialogue.reject	reject	serious	0.58	70
让我想想、考虑一下	dialogue.think	think	neutral	0.44	74
为什么、怎么回事、真的吗	dialogue.question	question	curious	0.52	55
也就是说、其实、比如	dialogue.explain	explain	neutral	0.56	63
建议、推荐、你可以试试	dialogue.recommend	recommend	smile	0.63	66
总之、综上、最后总结	dialogue.summary	summary	neutral	0.40	57
请进、这边请、跟我来	guidance.invite	invite	warm	0.74	82
稍等、等一下、请稍等	guidance.wait	wait	neutral	0.26	65
提醒、别忘了、记得	guidance.remind	remind	neutral	0.48	62
注意、小心、警告	guidance.warn	warn	serious	0.80	84
谢谢、感谢、多谢	social.thanks	thanks	warm	0.46	61
抱歉、对不起、不好意思	social.apology	apology	sorry	0.60	71
还好吗、没事吧、别担心	social.care	care	warm	0.50	64
太好了、成功了、真棒	emotion.celebrate	celebrate	excited	0.95	92
天啊、竟然、不会吧	emotion.surprise	surprise	surprised	0.88	86
难过、可惜、遗憾、糟糕	emotion.sad	sad	sad	0.82	83

2.  fay向数字人发送回复文字

代码块
JSON
复制
{"Topic": "human","Data": {"Key": "text","Value": "很高兴见到你", "IsFirst":1, "IsEnd":0}}



4.  fay向数字人发送询问文字

代码块
JSON
复制
{"Topic": "human","Data": {"Key": "question","Value": "很高兴见到你"}}



5.  fay向数字人发送实时日志文字

代码块
JSON
复制
{"Topic": "human","Data": {"Key": "log","Value": "很高... "}, "robot": "http://127.0.0.1:5000/robot/Thinking.jpg"}



6.  数字人向fay指定输出用户

代码块
JSON
复制
{"Username": "张三"}



6.  通知fay不用合成音频

代码块
JSON
复制
{"Output": false}




