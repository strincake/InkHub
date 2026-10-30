# 墨枢 InkHub 插件开发指南 · API 1

插件负责“什么时候生成什么画面”，墨枢负责优先级、展示时长、任务有效期和真实设备传输。插件不需要设备 IP，不需要 SDK 连接，也不需要墨枢接入密钥。

插件是本机 Python 代码，使用现有 Python 3.10+ 和 Pillow。墨枢按事件启动短期工作进程，支持普通或 async 的 `handle(ctx, event)`。不需要编写服务器，不需要维持心跳，不需要把图片经 HTTP 发回自己。

## 1. 最小插件

目录：

```text
my-clock/
  plugin.json
  main.py
```

`plugin.json`：

```json
{
  "api_version": 1,
  "id": "my-clock",
  "name": "我的桌面时钟",
  "version": "1.0.0",
  "description": "显示电脑本地时间和一句提醒。",
  "entry": "main.py",
  "triggers": {"startup": true, "interval_seconds": 60, "keys": true},
  "settings": [
    {"key": "title", "label": "屏幕标题", "type": "text", "default": "今天也慢慢来"}
  ]
}
```

`main.py`：

```python
from datetime import datetime
from screen_plugin import ImageDraw

def handle(ctx, event):
    # 每次事件都是新进程；用 ctx.state 保存跨事件数据。
    if event['type'] == 'key' and event['key'] == 'Confirm':
        ctx.state['confirmed'] = ctx.state.get('confirmed', 0) + 1

    image = ctx.canvas()  # 400×300 白底 Pillow Image
    draw = ImageDraw.Draw(image)
    draw.text((20, 25), ctx.settings['title'], font=ctx.font(24), fill='black')
    draw.text((20, 100), datetime.now().strftime('%H:%M'), font=ctx.font(60), fill='black')
    draw.text((20, 240), '电脑本地时间', font=ctx.font(16), fill='black')
    ctx.show(image, 'mono')
```

在工作区根目录打包：

```powershell
python scripts/pack_plugin.py my-clock my-clock.screen-plugin.zip
```

进入插件中心，安装 ZIP，然后点击启用。安装本身不会执行代码。默认一个插件对应一个内容来源；点击“显示规则”配置其优先级和展示行为。禁止把“已生成图片”当作“设备已经显示”。实际显示状态在屏幕总览和实时队列中确认。

现成参考：`plugins/desk-note/`，包含持久状态、定时、手动动作、按键、标准表单与自定义页面。

## 2. 清单字段

| 字段 | 含义 |
| --- | --- |
| api_version | 必须为整数 1 |
| id | 以小写英文字母开头，后续小写字母、数字、下划线、横线；最多 48 字符 |
| name / version | 名称和版本字符串，各 1～80 字符 |
| description | 可选介绍，最多 1000 字符 |
| entry | Python 入口相对路径，默认 main.py，必须存在于包中 |
| settings | 可选配置字段数组，最多 40 个；用于校验和默认值，不代表必须展示宿主控件 |
| homepage | 可选插件主页 HTML 相对路径，最大 256 KiB，必须在包中 |
| navigation_title | 可选侧栏标题，去除首尾空白后为 1～40 字符；默认使用插件名称 |
| settings_page | 旧版主页字段，继续兼容；同时声明时优先使用 homepage |
| triggers | 启动、定时、按键和自定义手动动作 |
| source_defaults | 可选默认显示规则，如 persistent、hold_ms、ttl_ms；用户仍可在“显示规则”中修改 |

清单放在 ZIP 根目录，不要再套一层目录。同 ID 插件不可直接覆盖；目前更新方式为卸载后安装，**卸载会删除该插件的设置和私有数据**。需要保留个人数据时先自行备份，不要把卸载当作无损升级。

## 3. 触发器与事件

```json
{
  "triggers": {
    "startup": true,
    "interval_seconds": 30,
    "keys": true,
    "actions": [
      {"id": "next-page", "label": "下一页"},
      {"id": "clear-count", "label": "重置计数"}
    ]
  }
}
```

| event.type | 附加字段及触发时机 |
| --- | --- |
| startup | 插件启用时；启用状态下重启墨枢也会触发 |
| interval | 定时或动态预约到期；间隔 1～86400 秒 |
| manual | action：用户点“立即刷新”时为 refresh；其他按钮为注册的动作 ID |
| key | key、action、revision：当前画面对应插件收到设备或模拟按键 |
| settings_changed | 已启用插件的设置保存成功时触发；未启用插件只保存，不执行 |
| displayed | 需声明 triggers.displayed=true；此来源收到真实 SDK 或模拟屏幕显示完成结果时触发，带 revision |
| display_settings_changed | 用户修改此来源的裁剪或灰阶设置时触发，旧渲染会被取消 |

`keys:true` 不会抢走其他来源的按键，只在本插件的有效任务实际显示时接收。key 是 Up / Down / Confirm；action 是 Short / Long，实际手势受设备固件限制。revision 是按键发生时的已显示画面版本。若按键处理期间屏幕已切到其他来源或已有更新状态，墨枢会丢弃这个迟到的交互画面，避免错误抢回屏幕。

每个插件始终串行执行事件；事件队列最多 32 个，重复定时事件合并。整个墨枢最多并行执行 4 个插件工作进程。手动或按键触发不是精确实时控制接口。每次执行最多 15 秒；失败不会拖停调度器，但可能保留上次画面，后续如何让出仍取决于来源显示规则。

定时是“上一次执行完成后再等多久”，不追赶漏掉的历史 tick。可以在一次处理里动态预约：

```python
def handle(ctx, event):
    # 例如刷新频率来自插件设置。
    ctx.trigger_after(ctx.settings['refresh_seconds'])
    # ...生成图片...
```

`trigger_after(1..86400)` 覆盖清单的下一次定时间隔；未调用则使用 interval_seconds。没有静态或动态定时配置时，完成后等待下一次手动、按键或设置事件。日程、文件夹变化、行情或远程接口变化，可用定时检查加 ctx.state 对比实现，不需要新的宿主协议。

## 4. 提供给插件的能力

| API | 用法 |
| --- | --- |
| ctx.settings | 经类型验证的插件配置字典 |
| ctx.state | 跨事件持久 JSON 状态；仅成功返回后由宿主保存，最多 64 KiB |
| ctx.canvas(color='white') | 创建 400×300 的 Pillow RGB 图像 |
| ctx.font(size=24) | 优先使用本机中文字体，再回退；可自行从包中加载字体 |
| ctx.show(image, format='mono') | 提交 Pillow Image 或图片路径；mono / gray4 / gray16 |
| ctx.play_wav(bytes_or_path, volume=90) | 每事件最多一个设备提示音；16 kHz 单声道 PCM16 WAV，0～100 整数音量、最长 3 秒且最多 96 KiB |
| ctx.trigger_after(seconds) | 预约下一次触发 |
| ctx.fetch_json(url, timeout=5, headers=None) | 请求 JSON；超时最多 10 秒，响应最多 1 MiB |
| ctx.package_dir | 插件代码/资源目录，建议只读使用 |
| ctx.data_dir | 此插件自己的私有文件目录，卸载时删除 |
| ctx.display | 当前只读显示信息：visible、revision、shown_at、now、format；时间值是调度进程内毫秒 |
| ctx.require_visible() | 将本次状态与画面提交绑定到当前已显示版本；生成期间失去展示权则丢弃，不重新竞争 |

`ctx.show` 可以接受 Pillow 图像或图片路径，提交尺寸必须为 400×300，缩放和裁剪由插件在提交前完成；输出为 PNG，编码最多 8 MiB。每次事件调用多次 show 时只保留最后画面。真实设备的色板量化、抖色和显示回执仍由原 SDK 负责，不需要插件重复抖色。

相册等“只在屏幕上才播放”的插件，不应设置一个始终运行的静态 interval。声明 displayed 触发器，在 displayed 且 ctx.display.visible 时调用 trigger_after；interval 开始时检查 visible，并调用 require_visible() 防止解码期间被抢占后仍发布。displayed 处理中不要再次 show，以免形成刷新循环。完整实现见 `plugins/local-gallery/`。

Pillow 图形对象、ImageDraw、ImageFont 可从 `screen_plugin` 导入。可使用 Python 标准库做 HTTP、时间、CSV、文件读写等，也可将纯 Python 辅助模块与静态资源放在 ZIP 中。墨枢不会自动安装 requirements 或执行安装脚本；额外依赖需作者声明并在本机环境中自行准备。

```python
from pathlib import Path
from screen_plugin import Image, ImageDraw, ImageFont

def handle(ctx, event):
    ctx.state['runs'] = ctx.state.get('runs', 0) + 1
    # 用 package_dir 定位打包资源，而不是依赖当前工作目录。
    image = Image.open(ctx.package_dir / 'assets' / 'background.png')
    # 私有文件适合缓存下载内容；请自行限制缓存大小。
    (ctx.data_dir / 'last-run.txt').write_text(str(ctx.state['runs']), encoding='utf-8')
    ctx.show(image, 'gray16')
```

模块全局变量不跨事件保留，线程或无限 while 循环不适合插件处理函数。持久数据放 ctx.state 或 ctx.data_dir。工作进程超时和禁用会终止当前执行，但它自行启动的其他子进程不属于可靠管理范围；请勿在插件中启动常驻后台进程。文件写入并不随失败自动回滚，只有 ctx.state 由宿主在成功返回后保存。

## 5. 自动设置表单

支持 text、password、textarea、number、boolean、select。例如：

```json
"settings": [
  {"key":"city", "label":"城市", "type":"text", "default":"上海"},
  {"key":"token", "label":"天气服务密钥", "type":"password", "default":""},
  {"key":"refresh_seconds", "label":"更新间隔（秒）", "type":"number", "min":5, "max":3600, "default":60},
  {"key":"show_date", "label":"显示日期", "type":"boolean", "default":true},
  {"key":"style", "label":"画面风格", "type":"select", "options":["简洁","详细"], "default":"简洁"}
]
```

字段 key 使用与插件 ID 相同的标识规则，同一插件不可重名。字符串最多 4096 字符，数值受 min/max 限制，下拉必须选声明的选项。建议始终给出有效 default。设置总 JSON 不应超过 64 KiB。宿主会拒绝未声明字段；复杂配置可放在声明为 textarea 的 JSON 文本中，由插件进一步解析。

password 只影响界面遮蔽，**本机设置文件没有加密**。设置页应使用人能读懂的名称、单位和说明，避免把内部变量名直接展示给用户。

## 6. 插件主页与设置入口

设置放在墨枢自动表单还是插件专属 UI，由开发者根据设置能力的复杂程度选择。简单配置可使用宿主表单，复杂交互可使用专属 UI；不要求同一套设置重复做两个界面，也不强制两种方式互斥。

插件主页是与屏幕总览、内容来源等内置页面同级的独立主内容页面。它可放便签编辑、文件列表、运行状态和手动操作等实际工作内容，也可按需加入部分或全部设置；主页只放工作内容、设置交给宿主表单也是正常用法。

清单声明 `"homepage":"home.html"` 且插件已启用时，宿主在现有“工作空间”导航项之后、底部运行信息之前增加“插件”类目，并注入该插件的导航入口。可用 `"navigation_title":"便签"` 指定标题，默认使用插件名称。插件中心也会显示“打开主页”。未提供主页或已禁用的插件不会注入入口；禁用或卸载当前打开的插件后返回屏幕总览。插件中心保留启用、宿主表单配置及卸载等管理入口。

每个 `settings` 字段可增加 `"host_ui":false`，隐藏该字段的宿主控件，但继续保留默认值、存储和类型校验。默认 `true`。所有字段均隐藏或未声明字段时，插件中心不显示“插件设置”。两个入口保存的是同一份配置；宿主表单保存时保留隐藏字段，主页发送 `save_settings` 时仍应提供完整对象。

```json
{
  "homepage": "home.html",
  "navigation_title": "便签",
  "settings": [
    {"key":"notes","label":"便签内容","type":"textarea","default":"","host_ui":false},
    {"key":"show_clock","label":"显示时钟","type":"boolean","default":true}
  ]
}
```

以上为清单片段：便签由主页编辑，时钟开关由宿主表单配置；若专属 UI 包含全部设置，可将各字段的 `host_ui` 均设为 `false`。配置仍必须声明，宿主会拒绝未声明字段。相同字段确有需要时也可在两处提供入口，不增加互斥模式开关。

主页文件必须自包含：内联 CSS、内联 JS，可使用 data: 图片；不依赖外部脚本或联网请求。宿主在完整主内容区使用 `sandbox="allow-scripts"` 的 iframe，不再放进设置弹窗。它不能直接访问父页面 DOM、控制令牌或其他插件设置。主页应使用响应式布局，适应桌面与窄屏内容区。切换到其他页面会销毁当前主页会话，返回时重新接收 context；未保存编辑不会跨页面保留。

旧插件的 `settings_page` 按主页打开，原字段默认仍显示在宿主表单；开发者迁移为 `homepage` 并按需设置 `host_ui` 即可消除不必要的重复。示例 `desk-note` 演示主页编辑便签、宿主管理显示选项，`local-gallery` 演示主页承担工作内容和全部设置。

通过 `postMessage` 进行受限交互：

```html
<input id="title">
<button id="save">保存</button>
<script>
let settings = {};
addEventListener('message', event => {
  if (event.source !== parent) return;
  const m = event.data;
  if (m?.protocol !== 'screen-plugin-ui-v1') return;
  if (m.type === 'context') {
    settings = m.settings;
    document.querySelector('#title').value = settings.title;
  }
  if (m.type === 'result') console.log(m.ok ? '成功' : m.error);
});
document.querySelector('#save').onclick = () => parent.postMessage({
  protocol: 'screen-plugin-ui-v1',
  type: 'save_settings',
  request_id: 'save-1',
  settings: {...settings, title: document.querySelector('#title').value}
}, '*');
parent.postMessage({protocol:'screen-plugin-ui-v1', type:'ready'}, '*');
</script>
```

子页面可发送：ready / get_settings、save_settings（完整设置对象）、run（action，默认 refresh）。父页面返回 context（此插件自己的信息、设置、state 和启用状态）或 result（request_id、ok、error）。运行完成后还会推送 state 消息，包含这个插件自己的最新 state；适合刷新相册文件列表等只读视图，不应因此重置用户尚未保存的表单。目标来源由宿主绑定的独立 iframe 决定，子页面不能用消息里的 ID 操作其他插件。对不透明 sandbox origin 发送消息需要 `'*'`；双方仍应校验 message source。保存设置会触发已启用插件生成新图，无需另发 run。

## 7. 安装、分享与状态保存

ZIP 最多 10 MiB，解压总量最多 16 MiB、单文件最多 8 MiB、成员最多 256 个。拒绝路径越界、绝对路径、盘符、反斜线、Windows 保留文件名、重名文件、链接和异常压缩比例。没有插件自动安装脚本。

“导出分享”仅导出插件代码与打包资源，重新验证后生成 ZIP，不包含填写的密钥、个人设置、ctx.state 或 ctx.data_dir。请勿在 main.py、plugin.json 默认值、资源文件中硬编码自己的密钥，否则它本来就是代码的一部分，会随包分享。

安装、启用状态、设置、私有数据和来源显示规则保存在当前调度配置旁的 `settings.plugins/`（使用 --config 时跟随该配置位置）。新安装默认禁用；启用状态跨重启保存，启动时自动恢复插件并按其 startup 声明触发。外部程序来源仍不跨重启恢复，两者生命周期独立。

禁用会取消当前处理、清空待处理事件并撤销来源。卸载先禁用，再等待工作进程退出，最后删除该插件的代码和私有数据。无其他候选时，屏幕可能保留最后像素，这不表示插件仍在运行。

## 8. 信任边界与排错

Python 插件拥有当前用户的本机文件和网络访问能力。工作进程隔离、超时、输出限制用于可靠性，不是操作系统安全沙箱。请只安装可信代码。宿主不主动将 API 接入密钥或任意环境变量传给插件，但可信插件仍能通过本机权限读取用户可访问的文件；没有声称能运行不可信插件。

print 输出会出现在“最近执行日志”（仅保留末尾约 8000 字符）；不要打印个人密钥。异常和超时显示在插件卡片上。出现导入错误时检查 Python/Pillow 与额外依赖；没有画面时检查插件是否启用、是否声明 startup 或已手动刷新、实时队列是否在等待更高优先级来源；按键不触发时确认当前屏幕实际显示本插件且任务有效。

## 9. 设备提示音与录音暂停

`ctx.play_wav(wav_bytes_or_path, volume=90)` 接受 WAV 字节或本机文件路径；插件应提供开关并默认关闭提示音。只在真正的新状态变化或明确的用户试听时请求声音，不要在定时心跳、重复扫描、重放历史或 displayed 回调中重复提醒。

```python
def handle(ctx, event):
    if event['type'] == 'manual' and event.get('action') == 'preview-sound':
        # 不 show：仅当本插件仍显示同一版本时播放，不抢占屏幕。
        ctx.play_wav(ctx.package_dir / 'assets' / 'waiting.wav', volume=40)
        return
    if new_recent_event and ctx.settings['sound_enabled']:
        ctx.show(image)
        ctx.play_wav(wav_bytes, volume=40)
```

一次执行最多调用一次 play_wav；再次调用会报错。SDK 格式为 16,000 Hz、单声道、16 位有符号 PCM，样本数 1～48,000，整个 WAV 最多 98,304 字节。API 验证后只写执行专属目录的 `frame.wav`；工作进程仅返回路径标识和音量，不在 JSON 中传输音频。宿主再次验证文件类型、文件大小和 RIFF/PCM 内容，读取后按原有规则清理本次执行目录。

同一处理同时 show 与 play_wav 时，声音绑定新画面的 revision，必须等这一版本收到显示完成才可播放。只请求声音时，执行开始和提交时必须仍是本插件的同一已显示版本；来源不在屏幕上、画面已更新或任务已到期就丢弃，不会因此抢屏。来源切换、禁用、版本更新会使旧声音失效；已经播放或丢弃的声音不会在来源返回时重放。禁用/更新期间的 worker 结果继续受 epoch 与取消规则保护。

宿主串行发送图片与音频。`/control/state` 的 `device.audio.status` 区分 `simulated`（只模拟调度，没有播放设备或电脑扬声器）与 `playback_ended`（SDK play 已收到设备 PlaybackEnded 结果）；后者的 reason 为 Completed、Stopped、Interrupted 或 Limit。生成 WAV、完成传输或模拟成功都不是实机听感验证。`failed` 或 `result_unknown` 会阻止后续全部图片和声音并清空待播请求；没有自动重发媒体。用户可选择限时自动重连设备；自动重连仍保留 failed / result_unknown 的媒体暂停状态。

宿主消费 RecordingStarted / RecordingFinished，仅维护 `device.recording`。录音时不开始新的图片/声音传输，待播声音直接丢弃，正在播放的声音由 SDK 标记 Interrupted；宿主不发送 stop，以免停止用户录音。已有图片传输可以完成。录音结束恢复正常调度，不重放录音期间的声音。不保存、不上传、不向插件传递录音内容。

回归验证：`python -m unittest discover -s tests/unit -p test_plugin_audio.py`；`tests/integration/audio-integration.py` 用临时配置、真实宿主/SDK 与 loopback 协议模拟器验证显示后播放、纯声音操作、录音暂停和未知/失败后停止发送。先以 `cargo build` 构建测试宿主；也可用 `SCREEN_SCHEDULER_TEST_BINARY` 指定待测宿主 exe。测试不使用已保存用户配置、不访问实体设备。

调度竞争补充：require_visible 的处理在生成过程中失去显示权时，宿主丢弃本次 state、画面与声音。如果清单声明静态 interval_seconds，仍按该间隔恢复后台检查；只有 displayed/trigger_after 的插件不保留本次动态预约，等重新显示再恢复。已排队按键还会核对最初 event.revision、执行开始的显示版本和提交时当前版本；不匹配时整个结果丢弃，不能先保存过期按键造成的选择状态。

声音提交还要求本次调用期间没有跨越全局暂停/恢复、设备连接切换或录音开始/结束；宿主以媒体 epoch 作校验。即使暂停又恢复都发生在 worker 返回前，也不会在恢复后播放旧提示音；恢复后的新手动试听仍正常。


## 多通道插件与图片尺寸约定

插件必须生成 **400×300 PNG**。`ctx.show` 与宿主均校验尺寸，不再替插件缩放、裁剪或留白。`fit` 不再是宿主显示规则；相册等需要此能力的插件，在自己的设置中定义并处理它。

清单增加 `"multi_channel": true` 后，一个插件可注册最多 32 个通道；未声明时保持原来一个插件一个通道的兼容行为。多通道插件在每次事件中调用 `register_channel` 声明完整通道集合；不再声明的通道被撤销，禁用或卸载插件会撤销全部通道。通道 key 必须稳定，格式与插件 ID 相同。每次事件重复声明同一 key 不会新建任务或刷新任务有效期；只有 `show` 才发布新画面。

```python
def handle(ctx, event):
    for item in ctx.settings['sources']:
        channel = ctx.register_channel(item['id'], item['name'],
            {'persistent': True, 'ttl_ms': 0, 'hold_ms': 0})
        if event.get('channel') and event['channel'] != item['id']:
            continue
        # 设置与业务状态由插件按通道组织；例如 ctx.state['albums'][item['id']]。
        if event['type'] in ('startup', 'settings_changed'):
            channel.show(channel.canvas(), 'mono')
```

`channel.display` 包含该通道的 visible、revision、shown_at、now 和 format。`key` 和 `displayed` 事件含稳定的 `event.channel`，按键只路由到实际显示的通道。轮播只应在 visible 为真时推进；调用 `channel.require_visible()` 并在事件上调用 `ctx.require_visible()`，可在渲染中被抢占时丢弃该事件的状态与画面。静态定时器仍会继续轮询。通道初始规则及设置变化时的规则通过 register_channel 的第三参数提交；宿主显示规则编辑器可单独调整并持久化每个通道。

清单设置类型新增 `json`，用于多来源等结构化配置，单字段 JSON 编码上限 32 KiB；用 `host_ui:false` 并由插件主页编辑。示例见 `plugins/local-gallery/`。插件禁用后，其主页入口从左侧导航消失，当前主页返回总览；插件中心保留管理入口。

### 宿主外观与内嵌页面尺寸

`context` 消息增加 `appearance: { mode: "system" | "light" | "dark", resolved: "light" | "dark" }`。切换外观时，宿主发送同协议的 `type: "appearance"` 消息。插件应校验 `event.source === parent` 与协议名，再使用 resolved 更新自身主题；屏幕画面颜色仍由插件设置管理，与工作台外观分开。

插件可发送 `{ protocol: "screen-plugin-ui-v1", type: "resize", height: number }` 上报内容高度。宿主只接受当前 iframe 发来的有限数值，限制在 320–20000px；切换后旧 iframe 的消息继续被拒绝。三个内置插件随包内嵌统一样式与控件，保持现有 CSP 不变，不依赖第三方样式/CDN。
