# GPT-SoVITS v1对接指南

来源：https://qqk9ntwbcit.feishu.cn/wiki/UokZwFkzDiPhfuko9xucIZ07nqh

# v1对接指南##

## 软件包准备
- Fay 
- GPT-SoVITS

## 实施步骤###

1. 安装最新的 Fay

请参照仓库说明安装并运行最新版本的 Fay。



2. 下载安装 GPT-SoVITS

请参照仓库说明安装最新版本的 GPT-SoVITS。

也可以直接下载一键包。

3. 运行 GPT-SoVITS

若安装的是一键包（dr：参考语音，dt ：参考语音的文本，dl ：语言）：

代码块
Plain Text
复制
runtime\python.exe api.py -dr "111.wav" -dt "" -dl "zh"

若直接正常手动安装（dr：参考语音，dt ：参考语音的文本，dl ：语言）：

代码块
Plain Text
复制
python api.py -dr "111.wav" -dt "" -dl "zh"

其他参数若想自定义，可以查看api.py了解，自行配置

4. 检查Fay上配置（tts\gptsovits.py）的GPT-SoVITS对接链接

（默认http://127.0.0.1:9880）

5. 修改配置文件system.conf

代码块
Plain Text
复制
tts_module=gptsovits

5. 运行 Fay



页面引用链接：
https://github.com/xszyou/Fay
https://github.com/RVC-Boss/GPT-SoVITS
