# 文档索引

从根目录 [README](../README.md) 开始构建和运行。

| 文档 | 内容 |
| --- | --- |
| [插件开发指南](guides/plugin-development.md) | 清单、事件、插件 API、独立主页和打包 |
| [外部接入协议](guides/protocol.md) | HTTP v1、UDP 托管、认证、交图、回执和按键 |
| [客户端说明](../clients/screen-scheduler-client/README.md) | Rust / Python 接入示例 |
| [随附插件](../plugins/README.md) | 三个插件的源码位置、用途和统一打包方式 |
| [Codex 工作搭子](../plugins/codex-companion/README.md) | 使用、任务状态、文件上报和提示音 |
| [本地相册](../plugins/local-gallery/README.md) | 多来源相册配置和轮播 |
| [依赖管理](development/dependencies.md) | 固定 SDK 快照、客户端和依赖更新方法 |
| [Windows 完整包验收](development/windows-release-verification.md) | 构建、安装、托盘、自启与测试边界 |
| [Windows 安装与发布](development/windows-release-plan.md) | 安装器、托盘、自启、离线运行环境及 CI/草稿 Release |
| [测试说明](development/testing.md) | 测试分层、依赖、执行顺序和产物 |
| [测试目录](../tests/README.md) | 单元、集成、浏览器、手动检查和模拟器的职责 |
| [数据与版本管理边界](development/data-boundaries.md) | 应提交的源码与应排除的本机数据 |
| [整理与验证记录](development/repository-preparation.md) | 本次迁移范围、检查与剩余事项 |

`archive/` 保存既有设计与计划，帮助理解历史决策。里面提到的旧交付路径和历史验证结果不代表当前验证结论；使用和开发以本索引中的现行指南为准。
