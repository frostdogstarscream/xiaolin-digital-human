# Qwen-tts 克隆

来源：https://qqk9ntwbcit.feishu.cn/wiki/GtTUwZxQdidBWnkLMXucCMBwnOg

Fay 接入 Qwen3-TTS 声音克隆

目录



1.
整体架构与原理

2.
环境与模型准备

3.
配置音色(声音克隆)

4.
启动服务并对接 Fay

5.
性能、监控与常见错误

第1节 整体架构与原理

欢迎来到 Qwen3-TTS 接入 Fay 的课程。整件事就四步,跟着做就行。

第一步,装环境。装 Python,装 CUDA 版的 PyTorch,装 Qwen3-TTS,下模型。

第二步,配音色。把你要克隆的那段音频和对应文字,丢进 speakers 目录。

第三步,起服务对接 Fay。Fay 改两处配置就好。

最后是排错速查,跑出问题随时回来看。



代码块
Plain Text
复制
# 客户端调用示例
import requests

resp = requests.post(
    "http://127.0.0.1:9882/tts",
    json={
        "text": "你好,我是小明。",
        "speaker_id": "default",   # 可选,服务端有默认值
        "language": "Chinese"      # 可选
    },
    timeout=180,
)
open("out.wav", "wb").write(resp.content)
# 响应是 audio/wav 字节流,直接写文件即可



第2节 环境与模型准备



[图片，未 OCR]





先说硬件。Qwen3-TTS 必须用 N 卡,CPU 跑不动。先看一下你的显卡驱动支持哪个 CUDA 版本,后面装 PyTorch 要对得上。

然后装 PyTorch,必须是 CUDA 版。直接 pip 装到的可能是 CPU 版,装完不能用。我们用官方那个 index 链接强制装 CUDA 版。装完用一行 Python 验证,is available 必须返回 True 才行。

模型推荐用 0.6B 那个版本,跑得快。从 ModelScope 或者 hf-mirror 下载都行。

最后强调一句,精度选 bfloat16,千万别选 float16,后者会让模型直接报错,这是个常见的坑。



代码块
Plain Text
复制
# 完整安装命令(按顺序执行)
conda create -n qwen3-tts python=3.12 -y
conda activate qwen3-tts
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# PyTorch 必须从官方 index 装 CUDA 版(看 nvidia-smi 选 cu121 或 cu118)
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 立刻校验,False 就卸载重装
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
# 期望: True 12.1

# 服务依赖
cd qwen_tts_server
pip install -r requirements.txt

# 模型(任选其一)
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base \
    --local_dir ./models/Qwen3-TTS-12Hz-0.6B-Base



第3节 配置音色(声音克隆)



[图片，未 OCR]





服务端有个 speakers 目录,你想要几个音色,就建几个子目录。目录的名字就是音色的 ID,客户端用这个名字来选。

每个音色目录里就两个文件。一个是 ref.wav,参考音频,三到十秒就够了,要干净人声,别有杂音和音乐。另一个是 ref.txt,这段音频对应的文字,标点要对齐。把这两个文件丢进去,音色就准备好了。

加完新音色不用重启。直接调一下 reload 接口,服务会重新扫描目录,把每个音色预处理一遍存到内存里。这就是为什么后面调用很快,因为重的活在启动的时候就做完了。



代码块
Plain Text
复制
# === ref.txt 示例 ===
# 内容必须和 ref.wav 念出来的完全对应,标点按实际停顿
你好,我是默认音色,我可以念任何文字。

# === 添加新音色流程 ===
# 1. mkdir speakers/xiaoming
# 2. 把准备好的 ref.wav 和 ref.txt 放进去
# 3. 调 reload (无需重启):
curl -X POST http://127.0.0.1:9882/speakers/reload

# === 客户端选音色 ===
# Fay 端 tts/qwen_tts.py 修改:
QWEN_TTS_SPEAKER = "xiaoming"



第4节 启动服务并对接 Fay



[图片，未 OCR]



把示例 config 复制一份改成 config.yaml,里面三个字段要改:模型路径、注意力实现方式、默认音色。注意力那个,没装 flash-attn 的就改成 sdpa。

启动很简单,python run dot py 加上 config 参数。日志按顺序往下跑,看到最后那行 Uvicorn running 就说明服务好了。中间任何一步报错都要先解决,别往下走。

Fay 这边只要两步。第一,打开 Fay 的 qwen tts 那个文件,改顶上几个常量,把服务地址和音色名字填进去。第二,Fay 的配置文件 system dot conf 里,把 tts module 改成 qwen。重启 Fay,你说话它就用新音色回你了。



代码块
Plain Text
复制
# === Fay 端: tts/qwen_tts.py 顶部 ===
QWEN_TTS_URL = "http://127.0.0.1:9882"   # 跨机改成服务机 IP
QWEN_TTS_SPEAKER = "default"             # 服务端 speakers/ 下的目录名
QWEN_TTS_LANGUAGE = "Chinese"
QWEN_TTS_TIMEOUT = 180

# === Fay 端: system.conf ===
[key]
tts_module=qwen

# === 服务端: config.yaml 关键字段 ===
model:
  path: ./models/Qwen3-TTS-12Hz-0.6B-Base
  device: cuda:0
  dtype: bfloat16
  attn_implementation: sdpa     # 没装 flash-attn 就 sdpa
speakers:
  default: default              # 默认音色 ID



第5节 性能、监控与常见错误

每次合成,服务日志会打一行统计,关键看 RTF 这个数。RTF 小于 1,说明模型比实时还快,不会卡。RTF 大于 1 就麻烦了,音频生成跟不上播放,Fay 一定会一断一断。

RTF 太高怎么办,有三个办法。第一,装 flash attention 二代,Linux 一行命令搞定,Windows 要找社区编译的版本,版本号要一一对上。第二,换 0.6B 模型代替 1.7B。第三,Windows 上调不动了,要么换 WSL2,要么直接回去用 GPT 索维茨,别死磕。

说几个常见错误。报 cuda is available 返回 false 的,八成 PyTorch 装错版本了,卸载重装。报 device side assert 的,十有八九 dtype 写成 float16 了,改成 bfloat16。SoX 找不到那个警告,Windows 上不用管。Fay 报 speaker not found,curl 一下 speakers 接口看看有哪些音色。



代码块
Plain Text
复制
# 排错速查表

# 1) torch.cuda.is_available() == False
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 2) CUDA device-side assert triggered
# config.yaml: dtype: bfloat16  # 不要 float16

# 3) FlashAttention2 has been toggled on, but it cannot be used
# config.yaml: attn_implementation: sdpa

# 4) speaker '...' not found
curl http://127.0.0.1:9882/speakers      # 看实际加载到的列表
curl -X POST http://127.0.0.1:9882/speakers/reload

# 5) RTF 偏高,确认数据
# 看服务日志: tts: chars=NN audio=X.XXs synth=X.XXs RTF=X.XX

# 6) Windows SoX 警告
# 不用管,wav 推理不需要


