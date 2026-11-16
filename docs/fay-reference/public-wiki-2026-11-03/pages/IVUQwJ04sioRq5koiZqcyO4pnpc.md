# OMP: Error #15: Initializing libomp140.x86_64.dll, but found libiomp5md.dll already initialized.

来源：https://qqk9ntwbcit.feishu.cn/wiki/IVUQwJ04sioRq5koiZqcyO4pnpc

[图片，未 OCR]

在命令行中设置环境变量

对于 Windows

1.
打开命令提示符（CMD）或PowerShell。

2.
输入以下命令来设置环境变量（这将只影响当前打开的命令行窗口）：

代码块
Plain Text
复制
set KMP_DUPLICATE_LIB_OK=TRUE

1.
在同一个命令行窗口中运行您的程序，以确保程序运行时环境变量是有效的。

对于 Linux 或 macOS

1.
打开终端。

2.
输入以下命令来设置环境变量（这将只影响当前打开的终端窗口）：

代码块
Bash
复制
export KMP_DUPLICATE_LIB_OK=TRUE

1.
在同一个终端窗口中运行您的程序。


