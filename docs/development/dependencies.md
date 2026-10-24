# 依赖管理

## 设备 SDK

- 上游：<https://github.com/itopinion/zectrix-local-push-sdk>
- 基准提交：`c71412f3f1e1d039bf4f09b9e7867c4661ae1237`。
- 本项目引用：`vendor/zectrix-local-push-sdk`。
- 保存方式：整理时正在使用的源码快照，包括本地修改；不把该快照标成与上游提交完全相同。
- 实质本地差异：`tests/lan.rs` 在 Windows 下忽略关闭测试客户端触发的 UDP 错误 10054，使共享测试模拟器可继续接收下一会话。
- 本地 Git 工作区还有换行等文件状态差异；源码按实际文件复制。每个文件的 SHA-256 在 `SNAPSHOT.json` 中，未复制上游原有的发布校验清单与验证结果；已按当前快照重新生成 `SDK_MANIFEST.json`、`SHA256SUMS` 和本次 Windows 验证记录。

许可证为 SDK 自带的 MIT，Opus 声明位于 `LICENSES/Opus-COPYING.txt`。SDK 的 `.git`、`target/` 和本机环境未复制。

更新 SDK 时先确定要引入的上游提交，对照当前本地补丁，再更新源码、`SNAPSHOT.json`、根 `Cargo.lock` 和此说明。需要重新执行宿主、客户端和 SDK 自身测试；不得只改来源记录而保留另一版本源码。

## Rust 工作区

根 `Cargo.toml` 管理宿主和 `clients/screen-scheduler-client`。两者使用同一份 vendor SDK，根 `Cargo.lock` 固定解析结果。vendor SDK 保留独立清单与锁文件，可单独执行自己的测试。

常规构建使用 `--locked`，主动更新依赖时才更新锁文件。`build.ps1` 明确使用项目内的 `target/`，不读取旧工程的构建环境脚本。Rust、C++ 编译器、Windows SDK、CMake 属于用户开发环境，不放进仓库。

## Python 与浏览器

运行插件需要 Python 3.10+；`requirements.txt` 固定本次验证使用的 Pillow 版本。宿主调用 PATH 中的 `python`，因此请在准备好所需依赖的环境中启动宿主。

Python HTTP 客户端仅使用标准库。Node.js 与 Playwright 仅用于可选的浏览器回归检查，不是宿主运行依赖。浏览器检查可通过 `CHROMIUM_PATH` 指定已有浏览器，通过 `NODE_PATH` 使用已有 Playwright 模块。
