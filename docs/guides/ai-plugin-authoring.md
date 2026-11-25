# 使用 AI 编写墨枢插件

打开“插件与接入”，点击“AI 写插件”。描述画面、更新频率、按键操作及需要的设置，然后选择连接方式。

## API 服务

服务商选择会填入 Endpoint 和接口格式；填写账号可用的模型 ID 与 API Key 后即可生成。Endpoint 支持 Base URL 或完整 `/chat/completions`、`/messages` 地址。本地 Ollama 等免密服务可以不填 Key；远程服务要求 HTTPS。密钥不写入连接配置，刷新网页后需重填。

预设地址可编辑，地域或专用套餐的地址可能不同，请以自己账号的接入说明为准。参考：[OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat/create)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages)、[DeepSeek](https://api-docs.deepseek.com/)、[百炼 Base URL](https://help.aliyun.com/zh/model-studio/base-url)、[Kimi](https://platform.moonshot.cn/docs/guide/start-using-kimi-api)、[Gemini OpenAI 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[Ollama 兼容接口](https://docs.ollama.com/openai)。

## 本地 MCP

MCP 是工具协议，需要服务器提供可以调用模型并返回生成内容的工具。文件管理或搜索服务器不能直接代替模型。

- Streamable HTTP：启动服务后填写 `http://127.0.0.1:端口/mcp` 等本地地址，需要时填写令牌。支持 JSON 与 SSE 响应，不支持旧版独立 SSE 入口。
- stdio：填写可执行程序路径；启动参数为 JSON 数组，例如 `["C:\\tools\\server.py"]`；环境变量为字符串 JSON 对象。使用 Python 时程序可填 `python` 或解释器完整路径。令牌和环境变量不持久保存。

点击“连接并读取工具”，选择实际的生成工具，展开参数说明查看 schema。调用参数按该工具要求填写，必须同时包含两种占位符。例如接受 `prompt` 字段的工具可以填写：

```json
{"prompt":"{{instructions}}\n\n用户需求：{{prompt}}"}
```

宿主将说明和需求填入参数，工具应返回 `{"files":{"plugin.json":"...","main.py":"..."},"summary":"..."}`。可通过 MCP `structuredContent` 直接返回此对象，也可在文本内容中返回 JSON。连接超时或工具失败可修改配置重试。协议依据：[MCP transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)。

## 检查与交付

生成结果显示源码及 ZIP。宿主会检查路径、包大小、清单与 Python 语法，但不会执行代码，也不保证业务功能或设备效果。点击“查看安装预览”复用正常安装入口：新增包默认禁用；已有同 ID 包会明确提示更新并保留数据及原启用状态。检查后再确认安装。

“下载插件开发 Skill”包含 `inkhub-plugin/SKILL.md` 和完整开发指南，可用于外部支持 Skill 的 AI 工具。安装版也可下载，无需源码工作区。
