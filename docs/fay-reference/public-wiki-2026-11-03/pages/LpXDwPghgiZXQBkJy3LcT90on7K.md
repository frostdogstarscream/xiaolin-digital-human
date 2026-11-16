# Live2D 模型制作要求（简化版）

来源：https://qqk9ntwbcit.feishu.cn/wiki/LpXDwPghgiZXQBkJy3LcT90on7K



本文档用于指导外包制作 Live2D 数字人模型。本版为最小可用版本，仅满足基础对话场景。



一、技术规格





二、必需参数（Parameters）

参数 ID 请严格使用 Cubism 默认命名。





三、口型同步（LipSync）要求

程序会通过 ParamMouthOpenY 参数实时驱动嘴巴开合，模拟说话口型。该参数的值范围是 0（闭嘴）~ 1（张嘴最大）。

对嘴部建模的要求

•
ParamMouthOpenY = 0 时：嘴巴完全闭合，自然状态

•
ParamMouthOpenY = 1 时：嘴巴张到最大

•
中间值（0.2~0.8）应有平滑的过渡，不能出现跳变或形变异常

•
嘴部形变需要在 0~1 全范围内看起来自然，因为程序会输出各种中间值

建模细节建议

程序内部会产生以下几种典型开合度，请确保这些值下嘴型看起来合理：



重要约束

•
动作（motion）和表情（expression）中都不要对 ParamMouthOpenY 设置关键帧，否则会与程序的实时口型驱动冲突

•
如果嘴部有多个参数（如 ParamMouthForm 控制嘴型宽窄），可以保留，但 ParamMouthOpenY 必须留给程序独占



四、动作（Motions）要求

不需要表情文件，不需要情绪系统。只需要以下动作：

动作组结构



Idle 组（至少 1 个）

自然站立的待机循环动画，有轻微呼吸感。

TapBody 组（共 5 个动作）

程序按 数组下标（从 0 开始） 调用，顺序必须严格按下表排列：



动作制作要求

•
FadeInTime 和 FadeOutTime 设为 0.5 秒

•
动作时长 2~4 秒

•
动作结束后能自然过渡回待机姿态

•
动作中不要包含 ParamMouthOpenY 的关键帧，口型由程序实时驱动，写入会冲突



五、model3.json 结构要求

以 MyModel 为例：

代码块
JSON
复制
{
  "Version": 3,
  "FileReferences": {
    "Moc": "MyModel.moc3",
    "Textures": ["MyModel.2048/texture_00.png"],
    "Physics": "MyModel.physics3.json",
    "Motions": {
      "Idle": [
        { "File": "motions/idle.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }
      ],
      "TapBody": [
        { "File": "motions/listen.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 },
        { "File": "motions/speak.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 },
        { "File": "motions/think.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 },
        { "File": "motions/wait.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 },
        { "File": "motions/greet.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }
      ]
    }
  },
  "Groups": [
    {
      "Target": "Parameter",
      "Name": "EyeBlink",
      "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]
    },
    {
      "Target": "Parameter",
      "Name": "LipSync",
      "Ids": ["ParamMouthOpenY"]
    }
  ],
  "HitAreas": [
    { "Id": "HitArea", "Name": "Body" }
  ]
}

关键点：

•
Groups 中 EyeBlink 和 LipSync 必须声明，程序依赖这两个组实现自动眨眼和口型同步

•
TapBody 数组中的顺序必须是：聆听、说话、思考、等待、打招呼



六、目录结构

代码块
Plain Text
复制
MyModel/
├── MyModel.model3.json
├── MyModel.moc3
├── MyModel.physics3.json
├── MyModel.2048/
│   └── texture_00.png
└── motions/
    ├── idle.motion3.json
    ├── listen.motion3.json      # 下标 0 - 聆听
    ├── speak.motion3.json       # 下标 1 - 说话
    ├── think.motion3.json       # 下标 2 - 思考
    ├── wait.motion3.json        # 下标 3 - 等待
    └── greet.motion3.json       # 下标 4 - 打招呼



七、交付清单





八、注意事项

1.
ParamMouthOpenY 不要动：动作中不要对嘴巴参数设关键帧，程序实时驱动口型

2.
动作组必须叫 Idle 和 TapBody：程序按这两个名字查找

3.
TapBody 顺序不能变：程序按下标 0~4 调用，顺序错了动作就对不上

4.
EyeBlink 和 LipSync Groups 不能漏：没有这两个声明，自动眨眼和口型同步不会生效
