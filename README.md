# 墨枢 InkHub · Screen Scheduler

墨枢是运行在本机的 NOTE4 屏幕内容调度工具。它把便签、相册、任务状态和外部程序生成的画面接入同一条展示队列，统一管理优先级、展示时间、按键归属及设备连接。

项目采用 Rust 宿主、中文网页管理界面和 Python 插件。首次启动使用模拟屏幕；连接实体设备需要在管理界面中主动操作。

## 主要功能

- **屏幕调度**：五级优先级、最低展示时间、任务有效期、临时优先、长期来源空闲回落，以及实时展示队列。
- **设备管理**：黑白、四灰、十六灰输出，设备显示回执，按键回传及可选的限时自动重连。
- **插件中心**：通过 ZIP 安装、启用、配置和卸载本地插件；插件可提供独立主页，并按需要使用宿主设置表单。
- **本地相册**：一个插件管理多个文件夹来源，支持固定图片、顺序/随机轮播、留边/裁剪及屏幕按键翻图。
- **Codex 工作搭子**：跟随本机任务状态，显示像素角色、任务分页和可选提示音；其他 Agent 可通过本机文件上报状态。
- **外部程序接入**：HTTP v1 与原 SDK 的 UDP 托管入口，附 Rust / Python HTTP 客户端和示例。

## 环境准备

当前启动脚本面向 Windows。开发环境需要：

| 工具 | 用途 |
| --- | --- |
| Rust stable，MSVC 工具链 | 构建 Rust 宿主和客户端 |
| Visual Studio C++ Build Tools、Windows SDK | 编译和链接 Windows 原生依赖 |
| CMake | 构建设备 SDK 的 Opus 原生依赖 |
| Python 3.10+ 与 Pillow | 插件运行、图片处理、插件打包和 Python 测试 |
| Node.js 与 Playwright（可选） | 浏览器界面回归测试 |

请在能找到 `cargo`、C++ 编译器和 `cmake` 的终端中构建。Python 必须能以 `python` 命令启动；宿主会调用这个命令运行插件。

在项目根目录安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

Pillow 版本固定为本次整理时使用的版本；Rust 的依赖版本由根目录 `Cargo.lock` 固定。首次构建需要获取依赖，具备完整缓存后才可使用 Cargo 的 `--offline` 选项。

## 构建与启动

在项目根目录执行：

```powershell
./build.ps1
./start.ps1
```

也可以一次完成构建和启动：

```powershell
./start.ps1 -Build
```

正式优化构建使用 `./build.ps1 -Release`，随后运行 `./start.ps1 -Release`。脚本将构建产物统一放在本项目的 `target/` 下。

打开管理界面：<http://127.0.0.1:38476>。网页关闭后服务仍会运行；在侧栏点击“退出墨枢”才能正常释放设备并结束服务。已有旧实例时，请先从旧网页退出，再启动本目录中的实例。

需要直接运行或指定其他数据位置时：

```powershell
./target/debug/note4-screen-scheduler.exe --config ./settings.json
```

`--config` 指向设置文件；插件运行目录根据它生成，例如 `settings.json` 对应同目录下的 `settings.plugins/`。源码使用构建时的项目路径定位 Python worker，因此目前请在构建目录中使用；分发单个 EXE 尚不构成完整安装包。

启动脚本也支持 `-Config`、`-Port`、`-HttpBind` 和 `-SdkBind`，可为独立实例指定数据文件和端口。

## 第一次使用

1. 启动后先在模拟屏幕中检查队列和画面。
2. 运行 `./pack-plugins.ps1`，生成三个随附插件的 ZIP。
3. 在插件中心安装 `dist/plugins/` 中的插件，按需启用；新安装的插件默认不启用。
4. 本地相册从左侧插件主页添加文件夹来源；便签与 Codex 工作搭子也通过各自主页操作。
5. 需要使用实体 NOTE4 时，先退出其他占用设备的程序，在“我的 NOTE4”中填写设备地址并主动连接。
6. 对每个内容来源设置优先级和显示规则。

项目没有带入任何旧设备地址、接入密钥、个人相册目录、会话记录或已安装插件状态。首次运行会生成新的本机配置。

## 接口和端口

| 接口 | 默认地址 | 用途 |
| --- | --- | --- |
| 管理网页与 `/control/*` | `127.0.0.1:38476` | 本机管理 |
| HTTP v1 | `127.0.0.1:38477` | 外部程序注册、交图、回执和按键 |
| UDP 托管入口 | `127.0.0.1:32342` | 原 SDK 程序接入 |

服务默认绑定本机地址。HTTP 接入密钥在管理界面获取；管理接口与外部程序接口的认证方式不同。详见[接入协议](docs/guides/protocol.md)和[客户端说明](clients/screen-scheduler-client/README.md)。

## 项目目录

```text
screen-scheduler/
├─ src/                            Rust 宿主、调度、设备与插件管理
├─ web/                            中文管理界面（构建时嵌入宿主）
├─ python/                         Python worker、安装/迁移工具与 plugin_kit API
├─ plugins/                        三个随附插件的源码、主页和说明
│  ├─ desk-note/                   桌面便签与时钟
│  ├─ local-gallery/               本地相册
│  └─ codex-companion/             Codex 工作搭子
├─ clients/screen-scheduler-client/ Rust / Python HTTP 客户端及示例
├─ vendor/zectrix-local-push-sdk/   固定的设备 SDK 源码快照与许可证
├─ tests/                          Rust、Python、浏览器测试及本机模拟器
├─ scripts/                        插件打包等开发工具
├─ docs/                           使用、开发、整理记录和历史设计
├─ build.ps1 / start.ps1            本项目构建与启动
└─ pack-plugins.ps1                随附插件打包
```

`target/` 保存编译产物，`dist/plugins/` 保存可分发插件包，`artifacts/` 保存测试报告、截图和临时数据。它们与本机 `settings.json`、`settings.plugins/` 均由 `.gitignore` 排除。不要把已安装插件的私有数据目录当作插件源码分享。

## SDK 与依赖管理

设备 SDK 来自 [itopinion/zectrix-local-push-sdk](https://github.com/itopinion/zectrix-local-push-sdk)，以源码快照存放于 `vendor/`，宿主和 HTTP 客户端引用同一份快照。项目无需相邻 SDK 文件夹，也无需 Git 子模块初始化。

此快照保留整理时使用的本地版本，包括 Windows UDP 测试模拟器的修补。上游基准提交、文件校验值及差异说明见 [SDK 快照记录](vendor/zectrix-local-push-sdk/SNAPSHOT.json)与[依赖说明](docs/development/dependencies.md)。更新 SDK 时需要整体替换、记录来源并重新验证。

## 开发与验证

```powershell
cargo test --locked --workspace
cargo build --locked --workspace --examples
python -m unittest discover -s tests/unit -p "test_*.py"
./pack-plugins.ps1
python tests/integration/integration.py
python tests/integration/source-integration.py
```

更多集成测试、浏览器检查及各自环境要求见[测试说明](docs/development/testing.md)。本机模拟器验证用于确认软件协议行为，不能代替实体设备测试。各轮检查结果见[整理与验证记录](docs/development/repository-preparation.md)。

## 当前边界

- 当前没有系统托盘、自启动安装项或完整发布安装包。
- SDK 的 `Busy`、`ResultUnknown` 等失败会暂停发送；用户处理后明确继续，不自动重放未知结果。
- 提示音由插件提交、宿主统一播放，默认关闭；录音内容不保存或上传。HTTP/UDP 外部来源暂不支持音频。
- 插件是有本机权限的 Python 代码；网页 iframe 的隔离不能把 Python 插件变成安全沙箱。
- 本地设置以明文保存；Codex 工作搭子启用后会读取配置指定的本机会话元数据。
- SDK 支持的硬件与固件范围见 [SDK README](vendor/zectrix-local-push-sdk/README.md)。

## 文档与许可证

完整入口见[文档索引](docs/README.md)。设备 SDK、Opus 与工作搭子插件的已有许可证和声明均已保留，详见[第三方声明](THIRD_PARTY_NOTICES.md)。主项目尚未指定统一开源许可证，公开发布前应由项目所有者确定。
