# 随附插件

Release 构建会嵌入本目录的随附插件。每个随附插件首次进入当前安装时默认禁用，由用户在插件中心按需启用。已有插件版本和卸载选择会保留。开发构建通过插件中心手动安装。

| 插件 | 说明 | 主要能力 |
| --- | --- | --- |
| `desk-note` | [便签](desk-note/README.md) | 多便签、实时预览、自动保存、按键翻阅 |
| `local-gallery` | [本地相册](local-gallery/README.md) | 多文件夹来源、裁剪、灰阶、固定或轮播 |
| `codex-companion` | [Agent 工作搭子](codex-companion/README.md) | Codex、Claude Code、Gemini CLI、OpenCode 2 和通用上报 |
| `desk-weather` | 桌面天气 | 当前温度、今日高低温、降水概率 |
| `focus-timer` | 专注计时 | 专注和休息倒计时、暂停和继续 |
| `today-checklist` | 今日清单 | 每日重复事项、设备勾选、按本地日期重置 |

在项目根目录执行 `./pack-plugins.ps1`，ZIP 输出到 `dist/plugins/`。GitHub Actions 的 `InkHub-plugins` 产物也提供全部 ZIP。单独打包可使用：

```powershell
python scripts/pack_plugin.py plugins/desk-note dist/plugins/desk-note.screen-plugin.zip
```

安装包包含插件源码和资源，不包含 `settings.plugins/` 中的用户配置或私有数据。开发接口见[插件开发指南](../docs/guides/plugin-development.md)。便签与相册也可作为插件开发参考。

手动更新使用原有“安装插件 ZIP”入口：选择同 ID 的新包，校验后显示新旧版本，确认即可替换代码并保留设置、私有数据、显示规则与启用状态，无需先卸载。新增设置取默认值，已移除设置不再传给新代码；已有值与新清单不兼容时拒绝更新。

## 日常插件怎么用

- **桌面天气**适合低优先级常显。启用后在插件设置填地点名称、经纬度和更新间隔。默认地点为上海。天气查询仅向 Open-Meteo 发送配置的坐标，服务中断时在屏幕上标明上一次成功的数据。数据字段及服务条款见 [Open-Meteo](https://open-meteo.com/en/docs)。
- **专注计时**在左侧主页开始、暂停、继续或重置，时长由插件设置管理。网页按秒显示，墨水屏以分钟为单位更新。该画面显示时可以用设备确认键暂停或继续。暂停、结束或重置画面默认约 70 秒失效，倒计时状态仍保留在主页。
- **今日清单**在插件设置里每行填一件事。相同文字合并，最多 24 项。设备上下键选择，确认键勾选或取消，也可以在网页插件管理页使用对应动作。按电脑本地日期重置勾选。
