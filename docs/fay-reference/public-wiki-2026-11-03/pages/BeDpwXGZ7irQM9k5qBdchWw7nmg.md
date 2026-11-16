# duix（android）

来源：https://qqk9ntwbcit.feishu.cn/wiki/BeDpwXGZ7irQM9k5qBdchWw7nmg

硅基开源仓库(https://github.com/GuijiAI/duix.ai)对接Fay，实现android端数字人。对接思路是把fay android connector工程代码（https://github.com/xszyou/fay-android）集成到duix android工程代码，实现与Fay 10001双向的声音沟通接口的对接。具体操作如下：

screen-20240807-175851
00:52

1、下载两个仓库代码，并配置安卓环境，以确保两个工程都能在android studio上编译成apk.

2、修改duix对应代码：

增加权限

AndroidManifest.xml

把“播放声音按钮”改名为“停止”按钮

activity_call.xml

增加与Fay 10001音频流端口的对接逻辑

CallActivity.kt

增加Fay地址输入框和麦克风开关

MainActivity.kt

activity_main.xml

增加保存kv到文件的工具类

KVUtils.java

3、大功造成，运行时记得启动Fay（https://github.com/xszyou/Fay）哦。

test-debug.apk
55.75MB

(20241010更新)

完整工程（sdk上补充了播放状态检测）：https://pan.baidu.com/s/1BtzYH9Hnt7-qTDUjE_hefQ?pwd=trqf

网上采集到可用的模型：https://pan.baidu.com/s/1ELL9zRZu_AZ383EtfHSwjg?pwd=qb3j

注：duix并非免费商用产品，如需商用请与南京硅基公司联系。


