# 文字交互接口（5000）

来源：https://qqk9ntwbcit.feishu.cn/wiki/PNKFwVgUKig6fDkMH03cMPiInIb

目的：通个文本信息与fay联通



1.
类 GPT 接口

接口地址

•
http://127.0.0.1:5000/api/send/v1/chat/completions

•
http://127.0.0.1:5000/v1/chat/completions

对于所有兼容 GPT 的项目，只需将 base_url 配置为 http://127.0.0.1:5000，即可与 Fay 进行对接。

参数

Model

•
fay：非流式

•
fay-streaming：流式

•
llm：直通大语言模型，fay也不做记录

参考代码

代码块
Python
复制
import requests
import json

def test_gpt(prompt):
    url = 'http://127.0.0.1:5000/v1/chat/completions'  # 替换为您的接口地址
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer YOUR_API_KEY',  # 如果您的接口需要身份验证
    }
    data = {
        'model': 'fay-streaming',
        'messages': [
            {'role': '张三', 'content': prompt}
        ],
        'no_reply':False #是否不需要fay回复
    }

    response = requests.post(url, headers=headers, data=json.dumps(data), stream=True)

    if response.status_code != 200:
        print(f"请求失败，状态码：{response.status_code}")
        print(f"响应内容：{response.text}")
        return

    # 处理流式响应
    for line in response.iter_lines(decode_unicode=True):
        if line:
            if line.strip() == 'data: [DONE]':
                print("\n流式传输完成")
                break
            # 每一行数据以 'data: ' 开头，去掉这个前缀
            if line.startswith('data:'):
                line = line[5:].strip()
                # 将 JSON 字符串解析为字典
                try:
                    data = json.loads(line)
                    # 从数据中提取生成的内容
                    choices = data.get('choices')
                    if choices:
                        delta = choices[0].get('delta', {})
                        content = delta.get('content', '')
                        print(content, end='', flush=True)
                        
                except json.JSONDecodeError:
                    print(f"\n无法解析的 JSON 数据：{line}")
            else:
                print(f"\n收到未知格式的数据：{line}")

if __name__ == "__main__":
    user_input = "当前时间"
    print("GPT 的回复:")
    test_gpt(user_input)
    print("\n请求完成")
