# elevenlabs

来源：https://qqk9ntwbcit.feishu.cn/wiki/MS6ow8NjvirBLfkxengc6PtZnzd

Tip

•
1月23日消息，英国AI语音克隆创企ElevenLabs 1月22日宣布获得8000万美元B轮融资，由Andreessen Horowitz、Nat Friedman、Daniel Gross联合领投，红杉资本、SV Angel、Smash Capital、BroadLight Capital、Credo Ventures参投。至此，ElevenLabs估值达到11亿美元，成为新晋独角兽企业。单凭一项ai技术就能打入独角兽的企业不多。

•
支持中国银联支付（涉及到信用卡的专有信息随便填就可以了）。

1.进入官网，注册账号

https://elevenlabs.io/

2.创建您的声音，并可以进行测试

[图片，未 OCR]

3.在profile获取您的apikey，并记录

4.在ai_module下创建python文件，参考代码

代码块
Python
import requests
import time
from utils import util

class Speech:
    def __init__(self):
        self.api_key = "your_api_key"
        self.history_data = []

    def connect(self):
        pass

    def close(self):
        pass

    def __get_history(self, text):
        for data in self.history_data:
            if data[0] == text:
                return data[1]
        return None

    def to_speech(self, text, voice_id="your_voice_id", model_id="eleven_multilingual_v2", stability=0.5, similarity_boost=0.5):
        history = self.__get_history(text)
        if history is not None:
            return history

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost
            }
        }
        headers = {
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()  # 检查HTTP错误

            file_url = './samples/sample-' + str(int(time.time() * 1000)) + '.mp3'
            with open(file_url, "wb") as audio_file:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:  # 过滤掉保持连接的块
                        audio_file.write(chunk)

            self.history_data.append((text, file_url))
            return file_url
        except Exception as e:
            util.log(1, "[x] 文本到语音转换失败！")
            util.log(1, f"[x] 原因: {str(e)}")
            return None

if __name__ == '__main__':
    eleven_labs_tts = Speech()  # 初始化类实例
    text = "你好，我是菲菲"
    audio_file_url = eleven_labs_tts.to_speech(text)

    print("音频文件已保存:", audio_file_url)

voice_id，api_key 需要替换为您自己的

5.修改fay_core.py下引入的ms_tts_sdk 为自己创建的文件

from ai_module.ms_tts_sdk import Speech



其它声音克隆接口推荐：aliyun、序列猴子、云知声、azure、aws

离线克隆：https://www.bilibili.com/read/cv25192534/


