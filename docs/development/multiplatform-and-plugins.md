# 多平台构建与日常插件

1. 保留 Windows x64 安装版和便携版。在 GitHub Actions 增加 Ubuntu x64、macOS Intel 和 Apple Silicon 原生构建，提供可解压的运行包。各平台先运行测试，再上传产物。版本标签与 Cargo 版本一致时汇总为草稿 Release。
2. 便签在输入、增删、切换后自动提交，保留旧便签格式和立即保存入口。宿主合并编辑、按顺序写入，并在离开插件页面时提交最新版本。用浏览器验证失败重试、快速切换和多次编辑。
3. 工作搭子沿用本地收件目录，增加 Claude Code、Gemini CLI 和 OpenCode 的生命周期事件适配。用合成事件和模拟屏验证等待、恢复、结束和再次开始。
4. 首批日常插件为天气、专注计时和今日清单。沿用插件管理和调度规则，首次安装默认禁用。测试离线天气缓存、计时结束以及清单翻页和勾选。

## GitHub 构建产物

普通分支构建和拉取请求可在 Actions 的对应运行中下载产物。版本标签生成草稿 Release，已有同标签 Release 时保留原有资产。`InkHub-plugins` 产物提供单独的插件 ZIP。

Linux 和 macOS 包需要 Python 3.10+ 和 Pillow。解压后在 `InkHub` 目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run-inkhub
```

在浏览器打开 `http://127.0.0.1:38476`。Linux 数据默认保存在 `~/.config/InkHub`，若设定 `XDG_CONFIG_HOME` 则使用其中的 `InkHub` 目录。macOS 数据保存在 `~/Library/Application Support/InkHub`。两者都可以传入 `--config` 使用独立数据。Linux x64 包在 Ubuntu 22.04 构建。macOS 包供对应架构的电脑通过终端运行，当前不提供签名安装程序。Windows 包仍自带 Python，支持托盘和可选自启。
