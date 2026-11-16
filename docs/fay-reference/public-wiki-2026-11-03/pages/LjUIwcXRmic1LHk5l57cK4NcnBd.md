# MCP模块

来源：https://qqk9ntwbcit.feishu.cn/wiki/LjUIwcXRmic1LHk5l57cK4NcnBd

[图片，未 OCR]

2026/01/07升级：Fay支持向其它MCP客户端暴露自带及开启的工具： http://127.0.0.1:8765/sse

2025/12/31升级：修复mcp server进程管理的bug；修复不开启MCP工具无法使用预启动工具的bug。

2025/12/17升级：支持预启动工具运行结果保存到记忆；预启动工具及llm可调用工具单独开关。

2025/12/10升级：支持工具预启动，使用mcp工具重构知识库，补充窗口截图工具。

2025/10/15升级：全新的工具调用机制，实现ai ide级的工具调用稳定性。（参考openai codex cli的实现逻辑）

一、功能操作

添加、删除、连接、断开、刷新、管理、开关单独工具、支持工具预启动、支持向其它MCP客户端暴露自带及开启的工具



二、Fay内置MCP服务器

1、tools

功能：为fay提供常用工具

工具：add、echo、now、ping、upper

配置：

代码块
JSON
复制
{
        "id": 1,
        "name": "tools",
        "ip": "",
        "connection_time": "2025-12-10 20:52:40",
        "key": "",
        "transport": "stdio",
        "command": "python",
        "args": [
            "test/mcp_stdio_example.py"
        ],
        "cwd": "",
        "env": {}
    }



2、日程管理

功能：为fay提供日程管理功能，日程执行时会主动触发fay，以实现主动AI功能

工具：add_schedule、delete_schedule、get_schedules、send_message_to_fay、update_schedule

管理UI: http://127.0.0.1:5011 (fay连接mcp服务后就会自动启动此管理页面)

配置：

代码块
JSON
复制
{
        "id": 2,
        "name": "Fay日程管理",
        "ip": "",
        "connection_time": "2025-12-10 20:52:44",
        "key": "",
        "transport": "stdio",
        "command": "python",
        "args": [
            "server.py"
        ],
        "cwd": "mcp_servers/schedule_manager",
        "env": {}
    }

3、logseq

功能：连接logseq笔记工具，以实现个人笔记的管理及todo管理

工具：append_text_to_page、append_todo_to_page、create_page、get_pages_by_tag、save_asset、search_tag、search_text、update_task_status

配置：

代码块
JSON
复制
{
        "id": 3,
        "name": "logseq",
        "ip": "",
        "connection_time": "2025-12-10 20:52:46",
        "key": "",
        "transport": "stdio",
        "command": "python",
        "args": [
            "server.py"
        ],
        "cwd": "mcp_servers/logseq",
        "env": {
            "LOGSEQ_GRAPH_DIR": "D:/iCloudDrive/iCloud~com~logseq~logseq/第二大脑"
        }
    }





4、知识库

详见：
Yueshen RAG知识库

配置：

代码块
JSON
复制
{
        "id": 4,
        "name": "yueshen rag",
        "ip": "",
        "connection_time": "2025-12-10 20:52:52",
        "key": "",
        "transport": "stdio",
        "command": "C:\\Users\\Lenovo\\anaconda3\\envs\\rag\\python.exe",
        "args": [
            "mcp_servers/yueshen_rag/server.py"
        ],
        "cwd": "",
        "env": {
            "YUESHEN_CORPUS_DIR":"新知识库目录",
            "YUESHEN_PERSIST_DIR":"cache_data/chromadb_yueshen",
            "YUESHEN_AUTO_INGEST": "1",
            "YUESHEN_AUTO_INTERVAL": "300",
            "YUESHEN_AUTO_RESET_ON_START": "0",
            "YUESHEN_EMBED_API_KEY": "sk-xxxx",
            "YUESHEN_EMBED_BASE_URL": "https://api.siliconflow.cn/v1",
            "YUESHEN_EMBED_MODEL": "Qwen/Qwen3-Embedding-8B"
        }
    }



5、窗口截图工具

Window Capture MCP Server

功能：windows 窗口截图保存，本为量化交易agent截图保存当前盘面状态而设计的工具

工具：list_windows、capture_window

配置：



代码块
Bash
复制
{
        "id": 5,
        "name": "window capture",
        "ip": "",
        "connection_time": "2025-12-10 20:52:54",
        "key": "",
        "transport": "stdio",
        "command": "python",
        "args": [
            "mcp_servers/window_capture/server.py"
        ],
        "cwd": "",
        "env": {}
    }



三、获取更多的工具

1、github、gitee

2、modelscope



四、MCP 工具外部调用接口



本文整理 Fay 内置 MCP 管理服务（默认端口 5010）的外部调用接口，覆盖 MCP 工具调用与预启用工具调用。



基础信息



•
Base URL: http://127.0.0.1:5010

•
Content-Type: application/json

MCP 工具调用接口



调用指定服务器工具



POST /api/mcp/servers/{server_id}/call



请求体示例：

代码块
JSON
复制
{
  "method": "tool_name",
  "params": {
    "key": "value"
  },
  "is_prestart": false
}



说明：

•
is_prestart=true 会跳过工具启用状态检查（用于预启用调用）。

调用工具（自动选择在线服务器）



POST /api/mcp/tools/{tool_name}



请求体示例：

代码块
JSON
复制
{
  "key": "value"
}



获取指定服务器工具列表



GET /api/mcp/servers/{server_id}/tools



获取在线服务器工具列表（聚合）



GET /api/mcp/servers/online/tools



预启用工具调用接口



配置预启用工具



POST /api/mcp/servers/{server_id}/tools/{tool_name}/prestart



请求体示例：

代码块
JSON
复制
{
  "enabled": true,
  "params": {
    "query": "{{question}}"
  },
  "include_history": true,
  "allow_function_call": false
}



获取可运行的预启用工具列表



GET /api/mcp/prestart/runnable



调用单个预启用工具（自动连接服务器）



POST /api/mcp/servers/{server_id}/prestart/{tool_name}/call



请求体示例：

代码块
JSON
复制
{
  "params": {
    "query": "{{question}}"
  },
  "question": "用户问题",
  "keep_connection": true
}



批量调用所有预启用工具（自动连接服务器）



POST /api/mcp/prestart/call



请求体示例：

代码块
JSON
复制
{
  "question": "用户问题",
  "keep_connection": true,
  "server_ids": [1, 2],
  "tool_names": ["tool_a", "tool_b"]
}



说明：

•
question 必填，用于替换 params 中的 {{question}} 占位符。

•
server_ids 与 tool_names 为空时表示对全部预启用工具生效。

页面引用链接：
https://qqk9ntwbcit.feishu.cn/wiki/M5OewhhAliHYCWkUxP2cghPKn6b
