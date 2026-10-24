# 许可证与第三方声明

本项目保留既有组件各自的许可证与声明：

| 组件 | 来源及许可文件 |
| --- | --- |
| Zectrix Local Push SDK | [上游](https://github.com/itopinion/zectrix-local-push-sdk)；[MIT 许可证](vendor/zectrix-local-push-sdk/LICENSE) |
| SDK 使用的 Opus | [Opus COPYING](vendor/zectrix-local-push-sdk/LICENSES/Opus-COPYING.txt) |
| Codex 工作搭子插件 | [插件许可证](plugins/codex-companion/LICENSE)；[第三方声明](plugins/codex-companion/THIRD_PARTY_NOTICES.md) |

其他 Rust / Python / Node 依赖按各自软件包许可证使用。依赖的存在不意味着本项目拥有其版权，vendor 快照也不改变原许可。

主项目原创代码采用 MIT 许可证，见仓库根目录的 `LICENSE`（Windows 包中为 `licenses/InkHub-MIT.txt`）。本授权不替代第三方组件、字体及素材各自的许可证。

Windows 完整包还携带应用内 CPython、Pillow 和 Noto Sans SC 字体，相关许可随 `licenses/` 分发。版本、官方下载来源及校验值见 [Windows 依赖锁文件](packaging/windows/runtime-lock.json)。构建工具 Inno Setup 的许可副本也随包保留；本项目没有将其许可套用于主项目源码。
