# GPT-SoVITS V2、V3对接指南

来源：https://qqk9ntwbcit.feishu.cn/wiki/M5TMwNiTKihOWpkO2jlcrfYqnnc

# V2、V3对接指南##

## 软件包准备
- Fay 
- GPT-SoVITS(主分支或fast_inference_分支)

## 实施步骤###

1. 安装最新的 Fay

请参照仓库说明安装并运行最新版本的 Fay。



2. 下载安装 GPT-SoVITS(fast_inference_分支或者主分支)

请参照仓库说明安装最新版本的 GPT-SoVITS(fast_inference_分支或者主分支)。

3. 运行 GPT-SoVITS api

速度问题可以调整tts_infer.yaml的device为cuda

主分支：

代码块
Plain Text
复制
python api_v2.py

fast_inference_分支：

代码块
Plain Text
复制
python api_v3.py

4. 根据官方说明更改Fay上配置（tts\gptsovits_v3.py）

例：（参考音频、参考文本一定要按实际情况修改），速度问题可以调整batch_size

代码块
Plain Text
复制
  data = {
        "text": text,                   # str.(required) text to be synthesized
        "text_lang": "zh",              # str.(required) language of the text to be synthesized
        "ref_audio_path": "I:/GPT-SoVITS-beta0706/111.wav",         # str.(required) reference audio path.
        "prompt_text": "抱歉，我现在太忙了，休息一会，请稍后再试。",            # str.(optional) prompt text for the reference audio
        "prompt_lang": "zh",            # str.(required) language of the prompt text for the reference audio
        "top_k": 5,                   # int.(optional) top k sampling
        "top_p": 1,                   # float.(optional) top p sampling
        "temperature": 1,             # float.(optional) temperature for sampling
        "text_split_method": "cut5",  # str.(optional) text split method, see text_segmentation_method.py for details.
        "batch_size": 1,              # int.(optional) batch size for inference
        "batch_threshold": 0.75,      # float.(optional) threshold for batch splitting.
        "split_bucket": True,         # bool.(optional) whether to split the batch into multiple buckets.
        "speed_factor":1.0,           # float.(optional) control the speed of the synthesized audio.
        "fragment_interval":0.3,      # float.(optional) to control the interval of the audio fragment.
        "seed": -1,                   # int.(optional) random seed for reproducibility.
        "media_type": "wav",          # str.(optional) media type of the output audio, support "wav", "raw", "ogg", "aac".
        "streaming_mode": False,      # bool.(optional) whether to return a streaming response.
        "parallel_infer": True,       # bool.(optional) whether to use parallel inference.
        "repetition_penalty": 1.35    # float.(optional) repetition penalty for T2S model.
    }

5. 修改配置文件system.conf

代码块
Plain Text
复制
tts_module=gptsovits_v3

5. 运行 Fay



页面引用链接：
https://github.com/xszyou/Fay
https://github.com/RVC-Boss/GPT-SoVITS
