# Codex 工作搭子 · 墨枢 InkHub 插件

这是原 NOTE4 本地宠物的原生插件重写。只需 Python 标准库、Pillow 和墨枢 API 1；不依赖原宠物 exe、旧网页服务、Hub 或相邻源码目录。

## 安装与使用

1. 先构建并运行本仓库当前版本的墨枢。提示音需要新增的 `ctx.play_wav` 宿主能力，不能使用迁移前的宿主二进制。
2. 在仓库根目录打包：`python scripts/pack_plugin.py plugins/codex-companion dist/plugins/codex-companion.screen-plugin.zip`。
3. 在插件中心安装 ZIP。安装默认不启用，不执行插件代码。
4. 在插件中心启用插件后，打开左侧「Codex 工作搭子」主页，按需设置跟随目录、动画、过期阈值和提示音。
5. 默认会话目录为当前用户的 `.codex/sessions`。宿主不会继承所有环境变量，非默认 CODEX_HOME 请在主页显式填写会话目录。
6. 先使用墨枢模拟屏幕观察画面。真实设备连接、优先级、显示时长、灰阶、裁剪统一在宿主管理；不再提供插件自己的设备地址或首次推送勾选框。

不要同时让原本地宠物和墨枢占用同一设备。此插件不会停止旧程序、搬迁旧凭据或自动接管设备。旧配置也不会自动导入。

## 保留的行为

- 本机 Codex 主会话跟随：工作、等待输入、恢复、完成、停止；排除子代理的复制历史。
- 以同一聊天的最新轮次为准。异步问题收到 `accepted` 不等于用户已经回答；等待真实回答后才恢复。
- 最近七天、最多 24 个主会话的有界增量扫描。启动读取尾部而非完整巨型历史；无法确认的记录显示未知，不猜测完成。
- 四项以内选择任务，超过四项按页切换；心跳不改变列表顺序。确认键恢复自动跟随。
- 保留原像素宠物、工作键盘、等待表情、完成庆祝及出错表情；主体采用最后确认的居中布局，底部横线 y=271、说明 y=285。
- 动画只在本插件可见且上次显示完成至少 2.5 秒后推进；空闲和无变化时不反复发布同一画面。
- 本机持久状态、单独设置主页、标注清楚的演示状态和提示音试听。
- 通用 Agent 与权限审批通知使用本地事件收件目录，不启动额外服务，不安装 Hook。

## 提示音

默认关闭。开启后等待用双音、完成用三音；只对最近有效状态变化提醒，启动重放、心跳和相同序号不重复响。

声音为本机合成的 16 kHz 单声道 PCM16 WAV，由墨枢统一发送。只有对应插件画面实际取得展示权后才播放；切换、禁用、过期或录音期间丢弃失效声音。试听也只作用于当前显示的插件，不抢占其他来源。

模拟屏幕的声音结果为 `simulated`，不代表设备发声。真实回执在总览的 `device.audio` 中；设备听感仍需实际观察。本次迁移不包含语音识别、TTS 或录音保存/上传。

## 其他 Agent 上报

先启用插件，在主页复制「本机收件目录」。示例路径仅占位，需换成主页显示的实际值：

```powershell
python report.py --inbox "<主页中的收件目录>" --task my-task-001 --seq 1 --status working --title "整理资料" --agent Agent
python report.py --inbox "<主页中的收件目录>" --task my-task-001 --seq 2 --status waiting --title "整理资料" --detail "需要选择输出格式"
python report.py --inbox "<主页中的收件目录>" --task my-task-001 --seq 3 --status working --title "整理资料"
python report.py --inbox "<主页中的收件目录>" --task my-task-001 --seq 4 --status done --title "整理资料"
```

`report.py` 从本插件源码目录或安装目录调用；它只写入原子 JSON 文件，不联网、不操作设备。`status` 支持 working / waiting / done / error / stopped / unknown。未知进度省略 `--progress`；已结束任务重开时使用新的任务标识。进行中任务至少每分钟上报一次真实心跳。`--source` 可隔离不同 Agent，但不可使用保留的 codex/demo 命名空间。

权限审批可使用以下事件，用户仍需在对应 Agent 内审批：

```powershell
python report.py --inbox "<主页中的收件目录>" --approval PermissionRequest --thread chat-001 --turn turn-001 --request request-001 --tool Bash --title "整理资料"
python report.py --inbox "<主页中的收件目录>" --approval PostToolUse --thread chat-001 --turn turn-001 --request request-001
python report.py --inbox "<主页中的收件目录>" --approval Stop --thread chat-001 --turn turn-001
```

审批信号必须为当前新鲜事件；不会把过期通知当作当前请求。此工具不抓取工具参数、命令文本、问题或答案。

## 状态与文件边界

宿主在成功处理后保存 `ctx.state`。本插件仅保存任务名称/状态、生命周期标识、有限游标、事件回执和设置；不保存原始会话、问题答案、工具参数或凭据。标题会显示到设备，仍应避免包含私人内容。

任务历史最多保留最近 32 项且受字节预算限制；页面只展示最近 12 项摘要。缓存不是完整审计日志。异常或超大收件文件进入有界隔离区，防止阻塞正常事件。接收回执在下次已提交事件中确认后才删除文件，避免处理失败时丢失上报。

导出分享只包含此目录的源码和资源，不含插件私有状态/本机收件目录/用户设置。卸载插件会删除宿主中的设置和私有数据，升级前应按宿主文档备份；不把卸载称为无损升级。

## 开发验证

在仓库根目录执行：

```powershell
python -m unittest discover -s tests/unit -p "test_companion*.py"
python scripts/pack_plugin.py plugins/codex-companion dist/plugins/codex-companion.screen-plugin.zip
$env:SCHEDULER_BINARY = "<包含音频接口的墨枢 exe 绝对路径>"
python tests/integration/companion-integration.py
```

完整集成测试使用临时配置、合成 Codex 会话和本机模拟屏幕，不读取个人会话，也不访问实体设备。音频协议模拟器另见仓库 `tests/integration/audio-integration.py`。
