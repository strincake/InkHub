# 测试说明

所有命令均从仓库根目录执行。先安装 `requirements.txt`，准备 Rust / C++ / CMake 环境。

## 1. 编译与单元测试

```powershell
cargo test --locked --workspace
cargo build --locked --workspace --examples
cargo test --locked --manifest-path vendor/zectrix-local-push-sdk/Cargo.toml
python -m unittest discover -s tests/unit -p "test_*.py"
```

Python 单元测试统一放在 `tests/unit/`，一条 discovery 命令覆盖插件、相册、迁移、工作搭子和音频。SDK 自身测试单独执行，不属于根工作区的 `--workspace`。Windows 下不要在集成测试运行宿主时重新编译同名 EXE。

## 2. 生成插件包

```powershell
./pack-plugins.ps1
```

生成 `dist/plugins/desk-note.screen-plugin.zip`、`local-gallery.screen-plugin.zip` 和 `codex-companion.screen-plugin.zip`。集成和浏览器检查使用这些源码包，不依赖旧工程已有的 ZIP。

## 3. 集成检查

```powershell
python tests/integration/integration.py
python tests/integration/source-integration.py
python tests/integration/plugin-integration.py
python tests/integration/channels-integration.py
python tests/integration/reconnect-integration.py
python tests/integration/companion-integration.py
python tests/integration/audio-integration.py
python tests/integration/host-races-integration.py
```

`tests/integration/source-integration.py` 还使用客户端 Rust 示例，请先执行上面的 `cargo build --workspace --examples`。相册的现行集成入口为 `tests/integration/channels-integration.py`。

测试默认使用 `target/debug/note4-screen-scheduler.exe`；可用 `SCHEDULER_BINARY` 指定其他构建。音频及竞争测试兼容 `SCREEN_SCHEDULER_TEST_BINARY`。测试创建临时配置，使用模拟屏幕或 loopback UDP 模拟器，不读取默认个人配置或连接实体设备。

## 4. Release 内置插件检查

```powershell
./build.ps1 -Release
python tests/integration/builtin-plugins-integration.py
```

该专项默认使用 Release EXE，验证全新配置自动安装三个插件、全部禁用且未执行，重启保留禁用/卸载选择，并保留已有同 ID 包。普通 Debug 测试仍使用空白插件环境。安装初始化标记位于本机 `settings.plugins/builtin-plugins.initialized.json`，不纳入源码。

## 5. 浏览器检查（可选）

安装 Playwright 模块和 Chromium，例如：

```powershell
npm install --no-save --package-lock=false playwright@1.62.1
npx playwright install chromium
node tests/browser/spatial-browser-check.cjs
node tests/browser/channels-browser-check.cjs
node tests/browser/companion-browser-check.cjs
```

上述三组检查覆盖当前空间布局、多来源相册与工作搭子。其他现行专项脚本为 `tests/browser/ui-browser-check.cjs`、`tests/browser/queue-controls-browser-check.cjs`、`tests/browser/source-controls-browser-check.cjs`，保留各自功能的详细断言。

`tests/archive/browser-check.cjs` 是旧版添加来源界面与单文件夹相册的历史测试，已由现行六组浏览器检查覆盖相应功能，不作为当前执行入口。

`tests/manual/spatial-live-smoke.cjs` 是**手动检查现有运行实例**的脚本，会修改 `38476` 端口服务的主题等状态，不纳入自动迁移验证。

可以通过 `NODE_PATH`、`CHROMIUM_PATH` 指定本机已安装模块和浏览器，不把安装位置写入共享源码。

## 产物与证明范围

插件安装包写入 `dist/plugins/`。Python 集成报告与预览写入 `artifacts/tests/integration/`，浏览器截图与报告写入 `artifacts/tests/browser/`，临时数据写入 `artifacts/tmp/`。这些文件均忽略提交；中断后也不会散落到项目根目录。历史整理产物在 `artifacts/history/`。

本机模拟测试证明队列、插件、客户端和设备协议处理路径；不能证明真实 NOTE4 的显示、按键或音频效果。实际执行的命令、结果与限制记录在[整理与验证记录](repository-preparation.md)。

## Windows 完整包与安装器

先运行 `./scripts/package-windows.ps1`，再运行：

```powershell
python tests/integration/packaged-runtime.py
python tests/integration/windows-installer.py
node tests/browser/installed-settings-check.cjs
```

完整包测试隐藏系统 Python，验证自带解释器/字体、内置插件、重复启动、用户数据隔离和自启开关；安装器测试执行临时目录安装、覆盖、卸载并检查数据保留。它们会恢复测试前的自启注册项。浏览器测试同时确认关闭网页后服务仍运行。原生托盘测试在 Cargo 测试中验证菜单消息转发和窗口清理。
