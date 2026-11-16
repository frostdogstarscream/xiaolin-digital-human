# live2d网页数字人

来源：https://qqk9ntwbcit.feishu.cn/wiki/C5ORwSBGeiDibhkD4MdcPBHpnih

Live2D工程对接Fay数字人框架

•
课程ID：fay-live2d-course

•
作者：郭泽斌

•
版本：1.0.0

•
章节数：8

•
课程制作工具：https://player.fay-agent.com/

•
课程包:

fay-live2d-course.zip
420.77KB

封面

[图片，未 OCR]

目录

1.
项目介绍与架构概览

2.
启动Fay后端

3.
启动Live2D前端

4.
WebSocket对接：连接Fay

5.
消息协议与数据结构

6.
语音播放与口型同步

7.
动作语义与表情联动

8.
总结与扩展方向

第1节 项目介绍与架构概览

讲稿

今天我们来讲解如何将一个Live2D前端工程对接到Fay数字人框架，让2D角色能够说话、做表情、做动作，成为一个有交互能力的数字人。

这个项目叫mate-human，是一个开源的Live2D数字人前端工程。它基于Live2D官方的Cubism SDK for Web搭建，使用TypeScript和Vite构建，通过WebSocket连接到Fay数字人后端，实现语音播放、口型同步、表情切换和动作驱动。

整体架构分为三层。第一层是Fay后端，负责对话、语音合成、情感分析和动作语义输出。第二层是WebSocket通道，Fay通过10002端口向前端推送音频和动作指令。第三层是Live2D前端，接收消息后播放语音、驱动口型、触发表情和动作。

这个项目的开源地址在屏幕上，Fay框架的开源地址是gitee.com/xszyou/fay。准备好了的话，咱们从启动开始讲起。

代码/文案

代码块
Plain Text
复制
# 项目开源地址
Live2D前端工程：https://gitee.com/garveyer/mate-human
Fay数字人框架：https://gitee.com/xszyou/fay

# 架构概览
┌──────────────┐    WebSocket     ┌──────────────┐
│   Fay 后端    │ ──────────────→ │  Live2D 前端  │
│              │   ws://10002    │              │
│ - LLM对话    │                 │ - 语音播放    │
│ - TTS语音    │  ← 音频/动作 →  │ - 口型同步    │
│ - 情感分析   │                 │ - 表情切换    │
│ - 动作语义   │                 │ - 动作驱动    │
└──────────────┘                 └──────────────┘

第2节 启动Fay后端

讲稿

首先我们来启动Fay后端。到Fay的Gitee仓库克隆源码，地址是gitee.com/xszyou/fay。

克隆完成后，进入fay目录。首先找到system.conf文件，如果没有，把system.conf.bak重命名为system.conf。然后根据你使用的大语言模型服务，配置里面的LLM地址和API Key。

接下来安装Python依赖。建议使用Python 3.12，先创建虚拟环境再安装。命令是pip install -r requirements.txt。

依赖安装完成后，运行python main.py启动Fay。启动成功后，你会看到控制台输出"Fay started"，同时会自动打开一个Web控制面板。

这里要注意几个关键点：第一，Fay启动后会在10002端口开启一个WebSocket服务，这就是我们Live2D前端要连接的接口。第二，你需要在Fay的控制面板里配置好TTS语音合成，否则前端收不到语音数据。第三，确保配置了大语言模型的接入，可以用LM Studio本地模型，也可以用在线API。

代码/文案

代码块
Plain Text
复制
# 1. 克隆 Fay 源码
git clone https://gitee.com/xszyou/fay.git
cd fay

# 2. 配置 system.conf
# 如果没有 system.conf，从备份创建：
cp system.conf.bak system.conf
# 然后编辑 system.conf，填入 LLM 地址和 Key

# 3. 创建虚拟环境并安装依赖
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 4. 启动 Fay
python main.py

# 启动后：
# - Web控制面板自动打开
# - WebSocket 服务监听 ws://127.0.0.1:10002
# - 在控制面板配置 TTS 和 LLM

第3节 启动Live2D前端

讲稿

接下来启动Live2D前端工程。先从Gitee克隆mate-human项目，地址是gitee.com/garveyer/mate-human。

克隆完成后，进入前端工程目录。具体路径是CubismSdkForWeb-5-r.4/Samples/TypeScript/Demo。这是一个标准的TypeScript加Vite工程。

先运行npm install安装依赖，然后运行npm start启动开发服务器。启动成功后，Vite会在5173端口提供服务，在浏览器打开http://localhost:5173就能看到Live2D角色了。

如果Fay后端已经在运行，前端会自动通过WebSocket连接到Fay的10002端口。连接成功后，你在Fay的控制面板发送一条消息，就能看到Live2D角色开口说话、做表情了。

如果浏览器因为自动播放策略阻止了音频，页面上会出现一个"Enable Audio"按钮，点击它即可解除限制。

代码/文案

代码块
Plain Text
复制
# 1. 克隆 Live2D 前端工程
git clone https://gitee.com/garveyer/mate-human.git
cd mate-human

# 2. 进入前端工程目录
cd CubismSdkForWeb-5-r.4/Samples/TypeScript/Demo

# 3. 安装依赖
npm install

# 4. 启动开发服务器
npm start

# 启动后访问：http://localhost:5173
# 前端会自动连接 ws://127.0.0.1:10002

# 项目结构
# Demo/src/
#   ├── main.ts           # 入口文件
#   ├── fayclient.ts      # Fay WebSocket 客户端
#   ├── lappmodel.ts      # Live2D 模型（含音频/动作）
#   ├── lipsync.ts        # 口型同步引擎
#   ├── lappview.ts       # 视图与吧台模式
#   ├── lappdefine.ts     # 常量定义
#   ├── live2d-action-adapter.ts  # 动作适配器
#   └── live2d-action-map.ts      # 动作映射表

第4节 WebSocket对接：连接Fay

讲稿

现在我们来看核心对接代码。整个对接的关键在fayclient.ts这个文件，它封装了一个FayClient类，负责WebSocket通信。

FayClient的构造函数接收两个参数：WebSocket地址和用户名。地址默认是ws://127.0.0.1:10002，也就是Fay后端的human接口。

连接建立后，客户端会立即发送一条握手消息，包含用户名和Output为true，告诉Fay"我是一个输出端，请把音频和动作数据推送给我"。

收到消息后，FayClient会把JSON解析成FayMessage对象，然后通过回调函数传给Live2D模型处理。

FayClient还内置了自动重连机制，最多重试5次，每次间隔翻倍，最长不超过30秒。这样即使Fay重启，前端也能自动恢复连接。

在lappmodel.ts中，模型初始化时会创建FayClient实例并注册消息回调，整个对接就这样串起来了。

代码/文案

代码块
Plain Text
复制
// fayclient.ts - Fay WebSocket 客户端

export class FayClient {
  private ws: WebSocket | null = null;
  private url: string;
  private username: string;

  constructor(url: string, username: string = 'User') {
    this.url = url;
    this.username = username;
  }

  connect(): void {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      // 握手：告知 Fay 我是输出端
      this.send({
        Username: this.username,
        Output: true
      });
    };

    this.ws.onmessage = event => {
      const message = JSON.parse(event.data);
      this.onMessageCallback?.(message);
    };

    this.ws.onclose = () => {
      this.scheduleReconnect(); // 自动重连
    };
  }
}

// lappmodel.ts 中初始化连接
this._fayClient = new FayClient(
  'ws://127.0.0.1:10002', 'User'

第5节 消息协议与数据结构

讲稿

接下来看Fay推送给前端的消息结构。每条消息是一个JSON对象，核心字段都在Data里面。

Key字段标识消息类型，值为audio时表示这是一条语音消息。Text是当前语音对应的文字内容。HttpValue是音频文件的HTTP下载地址，前端通过这个地址获取wav音频并播放。

Lips是口型数据数组，每个元素包含一个Lip字段（音素名称，如aa、ou、sil等）和一个Time字段（持续时间，单位毫秒）。前端根据这个数据驱动模型的嘴巴开合。

IsFirst和IsEnd用于标识一次完整回复中的首尾片段，因为Fay的TTS是流式的，一句话会被切成多个音频片段依次推送。

Sentiment是情感分析值，范围从负2到正2，表示这段话的情绪倾向。Action是动作语义对象，包含code、behavior、affect、intensity等字段，告诉前端应该做什么动作、配什么表情。

这套协议的设计使得Fay后端和前端完全解耦，Fay只输出语义，不关心具体模型的动作编号。

代码/文案

代码块
Plain Text
复制
    "Text": "这边请",
    "HttpValue": "http://127.0.0.1:5000/audio/xxx.wav",
    "IsFirst": 1,
    "IsEnd": 0,
    "Lips": [
      { "Lip": "sil", "Time": 80 },
      { "Lip": "aa",  "Time": 120 },
      { "Lip": "ou",  "Time": 100 }
    ],
    "Sentiment": 0.7,
    "Action": {
      "code": "guidance.invite",
      "behavior": "invite",
      "affect": "warm",
      "intensity": 0.74,
      "priority": 82,
      "matchedKeywords": ["这边请"]
    }
  },
  "Username": "User"
}

// TypeScript 接口定义 (fayclient.ts)
export interface FayMessage {
  Topic: string;
  Data: {
    Key: string;        // "audio" = 语音消息
    HttpValue?: string; // 音频下载地址
    Text: string;       // 文字内容
    Lips?: LipData[];   // 口型数据
    Sentiment?: number; // 情感值 -2~2
    Action?: FayAction; // 动作语义
    IsFirst: number;    // 首片段标记
    IsEnd: number;      // 末片段标记
  };
}

第6节 语音播放与口型同步

讲稿

语音播放和口型同步是数字人体验的核心。我们来看具体是怎么实现的。

当前端收到Fay的音频消息后，会把它加入一个音频队列。队列按顺序依次播放，保证多个语音片段不会重叠。每个片段包含音频URL、口型数据、文字内容和预估时长。

播放时，前端创建一个HTML5 Audio对象，通过HttpValue获取音频文件并播放。同时把Lips口型数据传给LipSync引擎。

LipSync引擎的工作原理是：根据每个音素的持续时间，计算当前时刻应该播放哪个音素，然后把音素映射成嘴巴张开程度。比如"aa"对应张嘴0.9，"sil"对应闭嘴0.0，"ou"对应0.8。

每一帧渲染时，LipSync引擎输出当前嘴巴的开合值，写入模型的ParamMouthOpenY参数，Live2D模型就会跟着说话了。为了让嘴巴运动更自然，还加了一个平滑因子0.3，避免嘴巴突然跳变。

如果浏览器阻止了自动播放，系统会检测到NotAllowedError错误，自动显示一个"Enable Audio"按钮，用户点击后即可恢复正常播放。

代码/文案

代码块
Plain Text
复制
// lipsync.ts - 口型同步引擎

// 音素到嘴巴张开程度的映射
const VISEME_MAP: Record<string, number> = {
  'sil': 0.0,   // 静音 - 闭嘴
  'aa': 0.9,    // 张嘴最大
  'ou': 0.8,    // 圆唇
  'oh': 0.7,    // 半圆
  'E': 0.6,     // 前元音
  'kk': 0.6,    // 舌根音
  'ih': 0.4,    // 短元音
  'PP': 0.1,    // 双唇音
  // ... 共15种音素
};

// 每帧更新嘴巴参数
update(deltaTime: number): number {
  // 找到当前时刻对应的音素
  const targetValue = VISEME_MAP[currentViseme];
  // 平滑过渡，避免跳变
  currentValue += (targetValue - currentValue) * 0.3;
  return currentValue;
}

// lappmodel.ts - 写入模型参数
const value = this._lipSync.update(deltaTime);
this._model.setParameterValueById(
  this._idParamMouthOpenY, value
);

// 音频队列播放
const audio = new Audio(nextSegment.url);
audio.onended = () => playNextSegment();
await audio.play();

第7节 动作语义与表情联动

讲稿

除了语音和口型，数字人还需要表情和动作。这部分是通过Fay的动作语义系统实现的。

Fay后端在config/action_rules.csv中维护了一张动作规则表，定义了20种标准动作。比如用户说"你好"，Fay会匹配到greeting.hello这条规则，输出behavior为nod（点头）、affect为smile（微笑）。

前端收到Action字段后，通过一个三层映射链来驱动模型。第一层是live2d-action-adapter.ts，它把语义动作翻译成模型能理解的动作组和表情名。第二层是live2d-action-map.ts，它定义了具体模型的映射关系，比如"invite"映射到TapBody的第21号动作，"smile"映射到F01表情。

如果没有匹配到Action，系统会回退到Sentiment情感值来驱动。比如Sentiment大于0.3就触发微笑表情，小于负0.7就触发悲伤表情。

这套设计的好处是：Fay后端完全不知道模型的具体动作编号，只输出"点头""微笑"这样的语义。换一个模型时，只需要修改前端的映射表，Fay那边完全不用动。

代码/文案

代码块
Plain Text
复制
// Fay后端：config/action_rules.csv（可用Excel编辑）
// code,behavior,affect,intensity,priority,sentimentHint,keywords
// greeting.hello,nod,smile,0.35,60,0.4,你好|您好|hello|hi
// guidance.invite,invite,warm,0.74,82,0.7,请进|这边请|跟我来
// emotion.celebrate,celebrate,excited,0.95,92,1.6,太好了|成功|真棒

// live2d-action-map.ts - Haru模型映射表
const BEHAVIOR_MOTION_MAP = {
  nod:       { group: 'TapBody', candidates: [1, 3] },
  invite:    { group: 'TapBody', candidates: [21] },
  wave:      { group: 'TapBody', candidates: [10] },
  think:     { group: 'TapBody', candidates: [11, 12] },
  celebrate: { group: 'TapBody', candidates: [6, 13] },
  // ...
};

const AFFECT_EXPRESSION_MAP = {
  smile: 'F01',     // 微笑
  serious: 'F02',   // 严肃
  sad: 'F03',       // 悲伤
  excited: 'F04',   // 兴奋
};

// 优先级链：Action > Sentiment > 默认
// 1. 有 Action → 触发对应动作+表情
// 2. 无 Action 有 Sentiment → 按情感值选动作
// 3. 都没有 → 播放待机动画

第8节 总结与扩展方向

讲稿

最后我们来总结一下整个对接的要点，以及未来的扩展方向。

这个工程对接了Fay的三个核心接口：第一是WebSocket 10002端口，用于接收音频和动作指令；第二是HTTP音频接口，通过HttpValue下载TTS合成的语音文件；第三是动作语义协议，通过Action和Sentiment字段驱动表情动作。

如果你想换一个自己的Live2D模型，需要做三件事：第一，把模型文件放到Resources目录下；第二，修改lappdefine.ts中的ModelDir指向你的模型目录名；第三，修改live2d-action-map.ts中的映射表，把behavior和affect映射到你模型的动作组和表情上。

未来可以扩展的方向有很多。比如把动作映射表从代码常量改成外部配置文件，方便非开发人员维护。比如给Action增加cooldown冷却时间和interruptible可中断属性，实现更复杂的动作排队。还可以接入摄像头实现面部追踪，让数字人"看着"用户。

项目的完整源码在gitee.com/garveyer/mate-human，欢迎star和贡献代码。到这里，咱们的课程就结束了，希望对大家有所帮助。

代码/文案

代码块
Plain Text
复制
# 对接的 Fay 接口总结

接口1：WebSocket ws://127.0.0.1:10002
  → 接收音频消息、口型数据、动作指令
  → 文件：fayclient.ts

接口2：HTTP 音频下载
  → Data.HttpValue 提供 wav 文件地址
  → 文件：lappmodel.ts (queueFayAudio)

接口3：动作语义协议
  → Data.Action (behavior/affect/intensity)
  → Data.Sentiment (情感值 -2~2)
  → 文件：live2d-action-adapter.ts

# 换模型只需三步
1. 放模型文件 → Resources/你的模型名/
2. 改配置     → lappdefine.ts: ModelDir = ['你的模型名']
3. 改映射表   → live2d-action-map.ts

# 开源地址
Live2D前端：https://gitee.com/garveyer/mate-human
Fay框架：  https://gitee.com/xszyou/fay



页面引用链接：
http://gitee.com/xszyou/fay
http://gitee.com/garveyer/mate-human
