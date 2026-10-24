# Windows 安装、托盘与发布

## 当前交付

Windows x64 安装程序、便携包和校验和已经可由同一条命令生成：

```powershell
./scripts/package-windows.ps1
```

该命令会构建 Release，下载/校验锁定资源，组装随包运行环境，再调用 Inno Setup。仅重打已有 Release 时可使用 `-SkipBuild`。开发机需要 Rust MSVC、Windows SDK/C++ Build Tools、CMake、Python 与 `requirements.txt`；最终用户不需要准备这些环境。

输出目录为 `dist/releases/`：

- `InkHub-<版本>-windows-x64-setup.exe`：当前用户安装程序。
- `InkHub-<版本>-windows-x64-portable.zip`：完整便携程序目录；用户配置仍独立保存。
- `SHA256SUMS`：两个文件的 SHA-256。

应用中的 `package-manifest.json` 记录源 Git commit、构建时工作区是否有修改以及文件哈希。正式发布应使用已提交的干净工作区。

## 安装与运行

安装器默认安装到 `%LOCALAPPDATA%/Programs/InkHub`，提供开始菜单和可选桌面快捷方式，不申请管理员权限，不默认开机自启。应用内带有独立 CPython、Pillow、中文字体及许可声明；不修改系统 Python 或 PATH，不在用户机器上运行 pip。

首次启动提供三个已安装插件，全部默认禁用。运行后在 Windows 通知区域驻留，双击图标或右键“打开管理界面”进入网页。菜单显示运行状态并提供“退出墨枢”。Windows 可能把新图标放在右下角的隐藏图标区域，需要展开查看。

关闭网页不会结束服务；从托盘或网页正常退出会停止插件、取消后续重连并关闭设备。重复启动会打开已有实例，而不是另开一个抢占端口和设备的进程。

## 开机自启

在屏幕总览的“连接与切换 → 软件设置”中勾选“随 Windows 启动”并保存。此设置默认关闭，只在 Windows 安装版/完整便携包中可用。

启用后在当前用户的 `HKCU/Software/Microsoft/Windows/CurrentVersion/Run` 中注册本安装目录的 `InkHub.exe --autostart`。登录 Windows 后驻留托盘，不自动弹出网页；取消勾选会移除该项。没有管理员级服务或全用户启动任务。

卸载只清除属于本安装目录的自启命令，不会删除另一份 InkHub 安装的命令。

## 文件与升级边界

- 应用目录：EXE、worker、内置迁移模板、运行环境和字体，由安装器管理。
- 用户目录：`%LOCALAPPDATA%/InkHub/settings.json`、`settings.plugins/`、`logs/`。
- 升级保留用户目录；卸载也保留配置和插件私有数据。
- 首次初始化标记随用户数据保存，重启或重装不会强行恢复已卸载的插件，也不会覆盖同 ID 的已有插件。
- 源码开发模式继续使用项目目录和 PATH 中的 Python；完整包通过 `runtime-layout.json` 标识，资源缺失时会报错，不能退回开发机源码路径掩盖打包问题。

当前已验证同版本覆盖安装的数据保留。跨版本升级仍应在每次正式发布前使用目标版本再次验收。

## 可复现依赖与供应链

`packaging/windows/runtime-lock.json` 固定 Python、Pillow wheel、字体、安装器和中文向导文件的 URL 与 SHA-256。字体与向导翻译同时固定上游源码提交。下载缓存位于忽略提交的 `artifacts/cache/windows/`。

`prepare-windows-assets.py --compiler` 还验证 Inno Setup 官方安装文件的 Authenticode 签名；本地编译器位于 `artifacts/tools/inno/`。安装包保留相关依赖和工具的许可文件。

本项目生成的 EXE/Setup 尚未购买或配置 Authenticode 签名证书；不能承诺消除 Windows 的未知发布者/SmartScreen 提示。首次公开发布前由所有者确定主项目许可证与签名策略。

## GitHub 自动化

`.github/workflows/windows-release.yml` 固定官方 Actions 的提交版本：

- 手动运行、默认不发布：测试、生成安装器、上传 Actions artifact。
- 推送 `v<版本>` 标签，或手动选择已有对应标签发布：使用对应源代码构建，版本检查通过后创建 Draft Release，附安装器、ZIP 和校验和。
- 上传 Release 的任务独立使用 `contents: write`；不把 token 或签名证书放在源码中。

当前仓库保持私有，工作流也不会改变可见性。公众下载需要后续明确将仓库改为公开，或使用单独的公开分发仓库。本次不推送版本标签、不创建公开 Release。

## 验证入口

```powershell
cargo test --locked --workspace
python -m unittest discover -s tests/unit -p "test_*.py"
python tests/integration/builtin-plugins-integration.py
python tests/integration/packaged-runtime.py
python tests/integration/windows-installer.py
node tests/browser/installed-settings-check.cjs
```

后三项会使用隔离目录、合成用户数据及临时自启设置，结束后恢复原注册项。原生托盘测试覆盖消息分发和窗口/图标的退出清理；桌面环境中的人工菜单观感仍可由用户安装后复核。测试结果和截图存放于 `artifacts/tests/`，不上传源码仓库。

参考：[Inno Setup](https://jrsoftware.org/isinfo.php)、[用户级安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)、[Python 应用本地分发](https://docs.python.org/3.14/using/windows.html)、[GitHub Release](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。
