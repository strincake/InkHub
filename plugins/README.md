# 随附插件

三个随附插件统一放在此目录。Release 构建自动将它们打包嵌入 EXE，首次启动安装缺失包且全部默认禁用；用户通过插件中心按需启用。已有同 ID 包与后续卸载选择不会被覆盖。开发构建继续通过插件中心手动安装和启用，不复制本机安装状态。

| 插件 | 说明 | 主要能力 |
| --- | --- | --- |
| `desk-note` | [桌面便签与时钟](desk-note/README.md) | 便签编辑、按键翻阅、时钟、宿主表单与独立主页 |
| `local-gallery` | [本地相册](local-gallery/README.md) | 多文件夹来源、裁剪、灰阶、固定或轮播 |
| `codex-companion` | [Codex 工作搭子](codex-companion/README.md) | 本机任务状态、分页、像素角色和可选提示音 |

在项目根目录执行 `./pack-plugins.ps1`，三个 ZIP 均输出到 `dist/plugins/`。单独打包可使用：

```powershell
python scripts/pack_plugin.py plugins/desk-note dist/plugins/desk-note.screen-plugin.zip
```

安装包包含插件源码和资源，不包含 `settings.plugins/` 中的用户配置或私有数据。开发接口见[插件开发指南](../docs/guides/plugin-development.md)。便签与相册也可作为插件开发参考。
