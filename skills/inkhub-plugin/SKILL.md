---
name: inkhub-plugin
description: Create or update InkHub NOTE4 Python plugins, including plugin.json, Pillow rendering, optional homepage, settings, and installable ZIP packages.
---

# 墨枢插件编写

为墨枢 InkHub 编写插件时，先读 [插件开发指南](references/plugin-development.md)。以该指南为 API 1 的依据；不要把其他插件系统的 API 套用到这里。

- 从用户需求确定画面内容、更新触发、设置和按键行为；沿用现有插件 ID 完成更新，新插件使用独立 ID。
- 根目录包含 `plugin.json` 和 Python 入口，按需增加主页；画面为 400×300 Pillow 图片。依赖以 Python 标准库、Pillow 和宿主 `screen_plugin` 为主。
- 实现 `handle(ctx, event)`，状态放 `ctx.state`，私有文件放 `ctx.data_dir`；事件是短期进程，不要依赖全局变量跨事件持久化。
- 通过 `ctx.show` 交图；宿主管理优先级、设备连接和显示队列。生成完成不表示实机已显示。
- 更新保留兼容设置和状态；需要迁移时由新代码处理。不要建议卸载来完成无损更新。
- 不把 API key、设备地址或用户数据写入分享包；不在安装阶段执行代码。
- 交付前校验清单和入口、Python 语法和 ZIP 路径。存在源码工作区时可用 `python scripts/pack_plugin.py <目录> <输出.zip>` 打包；ZIP 根目录直接放清单，不套外层文件夹。
- 交付 ZIP 和必要的使用说明；由用户在墨枢安装预览中确认安装/更新，再检查模拟屏幕、按键及真实设备。明确哪些测试实际做过。

如果调用方要求 JSON 文件映射，返回 `{"files":{"plugin.json":"文件内容","main.py":"文件内容"},"summary":"使用说明"}`，所有文件内容为 UTF-8 文本，不要输出 Markdown 围栏或 base64。
