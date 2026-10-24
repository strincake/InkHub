# 外部来源接入 v1 · 墨枢 InkHub

## 两种入口

| 入口 | 默认地址 | 适用情况 |
| --- | --- | --- |
| 旧 SDK 托管入口 | UDP `127.0.0.1:32342` | 原程序只改设备地址 |
| HTTP v1 | `http://127.0.0.1:38477` | 新程序，或替换发送 SDK |

管理页面仍是 `http://127.0.0.1:38476`。三个端口分工不同，不能互换。默认仅接收本机来源。需要其他电脑接入时，显式启动 `--http-bind 局域网IP:38477 --sdk-bind 局域网IP:32342`；管理页面仍只监听回环地址。若原应用只能填写 IP，网关必须使用默认 UDP 32342。不要把真实设备的 IP 填入接入地址。

**托管含义：原 SDK 的 show 成功、HTTP SDK 的 show 成功均只表示墨枢已完整接收。不会承诺已显示，也不等待来源取得展示权。** 实机结果在管理页面或 HTTP receipt 中查看；模拟运行的结果为 `simulated`，永不冒充 `displayed`。

旧程序不需要修改原 SDK 或刷设备固件。应持续运行并保持 SDK 保活、消费 next_event，正常退出 close。频繁连接、推图后立即 close 的一次性程序会立即撤销来源，因此必须改为保持连接，或改用 HTTP 客户端并让程序常驻。这是来源生命周期规则，并非一次性打印队列。

## 旧 SDK 支持范围

实现当前仓库 Zectrix LAN v1 的 INFO、CONNECT、PING、CLOSE、PALETTE、IMAGE_BEGIN/DATA/STATUS、STATE、普通 KEY 与确认，以及只读 STATUS 响应。状态值 3 / 成功结果在此虚拟设备中表示**已托管接收**。STATUS 的电量、充电与信号强度返回未知，不伪造真实设备状态。支持 AUDIO_BEGIN/DATA/END/STOP 短提示音托管：16 kHz 单声道 Opus，每帧 60 ms，最多 50 帧（3 秒），音量 0～100；必须先提交有效画面。录音不向外部程序开放。

不提供 mDNS 自动发现；请显式填写网关 IP 或 IP:端口。每个连接端点具有独立虚拟会话；15 秒没有新的有效 PING 则撤销来源。重复 PING、CONNECT 不延长租约。重复图像分片不会创建新任务，冲突分片或非法 zlib 会失败。仅支持本仓库协议版本，不能承诺兼容其他固件或第三方协议分支。

原 SDK 已经做过灰阶量化；网关按该会话色板将像素还原成可预览 PNG，再由输出 SDK 按真实设备当前色板发送。黑白位序保留；灰阶若换连接、换设备或色板不同可能重新映射，不承诺像素编码逐位相同。此实现不修改原 SDK，不绕过其显示完成确认。需要保留最高图像质量时，优先通过 HTTP 提交原始 PNG，让真实 SDK 最终处理。

## HTTP 鉴权与在线状态

管理页面“让其他程序接进来”可复制接入密钥。注册使用共享接入密钥；注册后返回仅属于此来源的会话密钥。密钥不放在 URL 中。HTTP 默认本机明文；跨机器只用于可信局域网。

1. `POST /v1/sessions`，`Authorization: Bearer <接入密钥>`，JSON `{"name":"我的生图程序"}`。
2. 返回 `id`、`token`、`lease_ms:15000`、`heartbeat_ms:5000`、`semantics:"accepted_by_scheduler"`。
3. 后续请求均用 `Authorization: Bearer <此会话 token>`。
4. 每 5 秒 `POST /v1/sessions/{id}/heartbeat`。心跳仅维持来源在线，不刷新任务有效期；提交新图才刷新任务有效期。
5. 正常退出 `DELETE /v1/sessions/{id}`。停止心跳 15 秒同样撤销来源。客户端不自动重新注册或抢占设备。

最多 64 个外部来源，来源仅存在于内存中，不跨调度程序重启保存。重启后客户端需要显式重新连接。来源名称是显示名称，不是认证标识；同名程序仍是独立会话。

## 提交、重试与实机状态

`POST /v1/sessions/{id}/frames/{sequence}`

- `Content-Type: image/png`；body 为原始 PNG 字节，不使用 base64 或本机文件路径。
- `x-image-format: mono | gray4 | gray16`，默认 mono。
- PNG 编码大小最多 8 MiB，解码尺寸最多 4096×4096。调度器按来源的留边/裁剪设置生成 400×300 画布。
- sequence 为从 1 开始的递增整数。同序号、相同原始字节与格式返回原回执，不刷新有效期，不重复发布；同序号不同内容返回 409。并发乱序旧请求不会覆盖已接受的新请求。
- 响应为 `{"sequence":1,"revision":1,"state":"accepted","error":null}`。客户端超时不代表未接收，应使用同序号查询或重试，不能自动换新序号重复提交。

`GET /v1/sessions/{id}/frames/{sequence}` 查询回执。每个来源保留最近 32 个回执；更旧的返回 404，不能据此断言从未执行。

| state | 含义 |
| --- | --- |
| accepted | 已接收，尚未开始发送 |
| displaying | 正在调用设备 SDK，等待显示结果 |
| displayed | 真实 SDK 收到设备显示完成回执 |
| simulated | 仅模拟显示完成 |
| superseded | 尚未发送便被同来源新状态替换 |
| expired | 尚未发送便因任务失效而退出竞争 |
| failed | SDK 返回明确失败，调度暂停 |
| result_unknown | 实机可能已执行，无法确认；调度暂停且按键暂不转交 |

已显示过不代表当前还在屏幕上；下一次内容可以覆盖它。一个来源只保存最新画面，回执不是历史图片存储。开始物理发送的操作不会被新图取消，完成后再按最新状态调度。

## 外部短提示音

HTTP：`POST /v1/sessions/{id}/frames/{sequence}/audio`，使用该来源会话 token；body 为原始 WAV，`Content-Type: audio/wav`，`x-audio-volume: 0～100`（默认 90）。WAV 必须为 PCM16、16 kHz、单声道、1～48,000 样本，文件最多 98,304 字节。必须先成功提交对应画面；画面仍须为该来源最新且有效版本。

返回 `{"sequence":1,"revision":1,"state":"accepted","semantics":"accepted_by_scheduler"}`。每个画面最多一条提示音，相同 WAV 和音量的重试返回原接收结果且不重播；同一画面提交不同声音返回 409。无画面回执返回 404，无效 WAV/音量返回 400，媒体暂停、录音、设备未连接或画面已被替换时返回 409。重试返回 accepted 仅表示原请求曾被托管，不表示仍待播或已播放。图像 receipt 仍仅表示图像状态；最新音频实际结果看管理状态 `device.audio`。

```python
receipt = device.submit(png_bytes)
device.play_wav(wav_bytes, sequence=receipt["sequence"], volume=60)
```

```rust
let receipt = device.submit(&png, ImageFormat::Mono).await?;
device.play_wav(receipt.sequence, &wav, 60).await?;
```

UDP：原 SDK `show` 后可调用 `play`，最长 3 秒。网关完整接收 Opus 后排入同来源、同画面版本的提示音；BEGIN 绑定版本和媒体状态，重复 END 不重复排队。缺帧、冲突分片、超长或暂停期间跨越的传输均丢弃，STATE 最后音频结果为失败（7）。STATE 成功（0）表示已托管接收，原 SDK `play` 返回 Completed 也沿用这一托管含义，不能当作实机播毕。STOP 只撤销该来源待播提示音，无法撤回已经交给真实设备的播放。未提供录音转发和 mDNS。

两种入口均等待对应画面显示完成后播放一次；新图替换旧版本、来源退出/心跳超时、全局暂停、录音、设备切换或结果未知会使旧待播声音失效，不会在恢复后自动重播。UDP 每次传输可提交一条新提示音，HTTP 每个画面只接受一条。此功能面向短提示音，长音频与流式播放尚未开放。

## 按键返回

`GET /v1/sessions/{id}/events?after=0`

返回 `{"cursor":1,"gap":false,"events":[{"cursor":1,"type":"key","key":"Up","action":"Short","revision":3,"at":12000}]}`。

- 仅实际显示且任务有效的来源接收按键。换图中或结果未知时不转交，防止送错应用。
- key 为 `Up`、`Down`、`Confirm`；action 为 `Short`、`Long`，具体手势以固件为准。录音不向外部程序提供。
- 客户端处理一个事件后，以下次请求的 after=该事件 cursor 确认消费位置；同一个来源只应有一个事件消费者。
- 保留最近 64 个事件。`gap:true` 表示读取过慢导致旧事件丢失，客户端应报告并重新同步，而不是静默假装完整。
- revision 指向按键发生时已显示的任务状态，用于应用判断迟到交互结果；普通 show 是独立状态更新，应用应避免用过时按键生成的图片覆盖较新业务状态。

## 便捷封装与最小迁移

Rust：`clients/screen-scheduler-client/`。保留源码中 `use zectrix_sdk::...` 的一种迁移方式：

```toml
[dependencies]
zectrix-sdk = { package = "screen-scheduler-client", path = "../screen-scheduler-client" }
tokio = { version = "1", features = ["full"] }
```

```rust
use zectrix_sdk::{Device, OpenOptions, ImageFormat};
// 设置环境变量 SCREEN_SCHEDULER_KEY，或使用 open_with_key(options, key)。
let device = Device::open(OpenOptions {
    target: Some("http://127.0.0.1:38477".into()),
    client_name: Some("我的生图程序".into()),
}).await?;
device.show_with_format(&png, ImageFormat::Gray16).await?;
// 持续运行，必要时消费 device.next_event().await?。
// 需要回执：submit 返回 Receipt；receipt(sequence) 查询真实结果。
// 不确定请求结果：last_sequence() 获取序号，submit_with_sequence 按原序号重试。
device.close().await?; // 仅在程序真正退出时调用。
```

常用类型 OpenOptions、ImageFormat、Event、Key、Error 沿用原 SDK 类型。兼容的是图像/按键调用方式，不是完整替代原 SDK：palette/status/录音及原 SDK 的 PCM play 接口未提供；短 WAV 使用新增 play_wav。使用这些功能的程序需要额外修改。

Python：将 `clients/screen-scheduler-client/python/screen_scheduler.py` 放进项目或加入模块搜索路径，无需第三方依赖：

```python
from screen_scheduler import Device, OpenOptions, ImageFormat
with Device.open(OpenOptions("http://127.0.0.1:38477", "我的生图程序")) as device:
    receipt = device.submit(png_bytes, ImageFormat.Gray16)
    # 继续主循环，按需 device.next_event(timeout=1) 并生成新图。
    # 查询 device.receipt(receipt["sequence"])；退出 with 会撤销来源。
```

两套客户端均自动发送心跳；生成画面循环自行保留。HTTP 不负责安装、启动或重启外部应用。


## API 1 插件声音（宿主内部）

插件 worker 可在结果中返回 `"audio":{"path":"frame.wav","volume":90}`，无声音时为 null。该 path 字段仅用于宿主 Python worker 协议；外部 HTTP 使用下述 WAV 字节接口，UDP 使用 Opus 分片，均不读取外部程序指定的本机路径。文件必须位于本次宿主生成的 UUID 执行目录；宿主只读取固定名称，拒绝链接、非普通文件和路径变体。WAV 限 98,304 字节、RIFF WAVE、PCM=1、16 kHz、单声道、16 位、1～48,000 个完整样本。工作目录仍在成功/失败/取消后按已有规则删除。

声音随图片提交时绑定该来源新 revision；纯声音提交则绑定执行开始时的可见 revision，提交时再次检查。宿主实际发送前校验来源启用、TTL、当前显示来源、当前显示 revision、最新来源 revision、全局暂停、录音和设备阻断状态；只消费一次。声音不能自行取得屏幕展示权。换图/播放都占用同一宿主媒体操作互斥；对应图片完成后才开始声音。

管理状态 `device.audio`：`idle`、`playing`、`simulated`、`playback_ended`、`failed`、`result_unknown`。模拟状态不会调用 SDK play；设备结果来自 SDK play 等待 PlaybackEnded。失败与未知结果使 `device.blocked=true` 并清空待播声音，阻止后续所有媒体；显式继续不会重放丢弃声音。`device.recording` 来自 SDK 录音开始/结束事件；宿主丢弃录音内容且不写入文件/插件状态/日志，录音期间暂停新媒体并丢弃提示音。
