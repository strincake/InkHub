# 独立项目整理与验证记录

## 目标与约束

按已确认的整理范围完成上传 GitHub 前的第一、第二步：建立独立项目、排除本机数据、整理文档、固定 SDK 和相关测试依赖、重写 README。保留现有产品行为与原目录；本阶段不初始化 Git、不创建远程仓库、不提交或上传。

## 实施计划

- [x] 梳理宿主、插件、客户端、SDK、构建和测试的目录依赖。
- [x] 使用白名单复制源码；排除设置、凭据、已安装状态、缓存、二进制、旧结果及临时目录。
- [x] 将设备 SDK 固定到 `vendor/`，保留实际本地差异、来源、许可证和文件校验值。
- [x] 将 HTTP 客户端和协议模拟器纳入项目，修复旧工程相邻目录引用。
- [x] 整理 `docs/guides`、`docs/development` 与 `docs/archive`，重写根 README。
- [x] 新增本项目构建、启动和插件打包脚本，以及 Git 忽略和换行规则。
- [x] 验证源码边界、文档链接、依赖解析、构建、测试和独立启动。

## 整理决策

设备 SDK 采用 vendor 源码快照，而非直接改成上游 Git 依赖：整理时其本地测试含 Windows UDP 修补，实际文件不能直接等同于远程提交。根宿主与 HTTP 客户端组成 Cargo 工作区，引用同一个 SDK。

保留根目录现有集成和浏览器检查入口，避免同时改动它们的导入结构；调整跨工程资源和构建产物路径。主集成测试中的旧版相册参数已改为当前多来源设置及通道状态，继续保留原有 14 项断言。三个随附插件仍从源码打包、经 UI 安装，不导入旧机器的安装状态。

历史文档放入 `docs/archive`。上游 SDK 的旧验证结果、发布校验和本机历史测试结果均不作为本项目当前验证证据。

## 验证结果

以下结果来自新项目目录中的实际执行：

| 检查 | 结果 |
| --- | --- |
| `cargo build --offline --workspace --examples` | 通过，Rust 客户端示例在本项目构建 |
| `cargo build --offline --locked --bin note4-screen-scheduler`、`./build.ps1` | 通过，宿主在本项目重新构建 |
| `cargo test --offline --locked --workspace` | 26 项通过，0 失败 |
| `cargo test --offline --locked --manifest-path vendor/zectrix-local-push-sdk/Cargo.toml` | SDK 单元 16 项、UDP 集成 10 项通过 |
| 根目录 Python 单元测试 | 22 项通过 |
| `tests/` Python 单元测试 | 27 项通过 |
| 三个随附插件打包 | 包结构校验通过，产物在 `dist/screen-scheduler/` |
| 八组集成检查 | `integration.py`、`source-integration.py`、`plugin-integration.py`、`channels-integration.py`、`reconnect-integration.py`、`companion-integration.py`、`audio-integration.py`、`host-races-integration.py` 全部通过 |
| 新启动脚本 | 使用含空格的临时配置路径、独立管理端口和随机接入端口启动，验证模拟模式、零已安装插件、写入指定配置和正常退出 |
| `.gitignore` | 11 类本机/产物路径被忽略，10 个代表性源码路径不被忽略；审计使用临时 Git 元数据，项目根目录无 `.git` |
| JavaScript 与 PowerShell | 所有现有浏览器检查入口、网页 JS 和三个 PowerShell 脚本语法通过 |
| SDK `scripts/verify.py` | 本快照重新生成的文件清单与 SHA-256 校验通过 |

本机验证使用已有 Rust、MSVC、CMake 工具链与依赖缓存；工具链不随源码复制。受限执行环境曾导致 Python 临时目录访问拒绝，改用正常用户权限后原测试通过。编译与运行同名 Windows EXE 需要顺序执行，避免运行中的文件被重新链接。

未在本轮执行浏览器交互回归，也未连接实体 NOTE4；相关界面、真实显示/按键/音频效果不能由上述结果替代。历史专项浏览器脚本已保留并修正资源路径，部分阶段性断言仍需按当前界面复核。

旧本机配置、已安装状态和个人数据未复制。新测试生成的 ZIP、报告、日志与构建产物在忽略范围内，项目根目录未创建默认 `settings.json` 或 `settings.plugins/`。报告汇总保存在本机 `dist/verification/`，不纳入源码。

## 后续阶段

待本次整理完成后，下一阶段才是初始化 Git、核对首次提交、选择远程仓库名称及公开性、连接并上传 GitHub。主项目许可证由所有者确定。
