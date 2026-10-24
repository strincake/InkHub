# 调度台 HTTP 客户端

Rust API 尽量保持原 Note4 SDK 的使用习惯：`Device::open`、`show`、`show_with_format`、`next_event`、`close`。自动维护来源心跳，不自动重连。`show` 成功表示调度台已接收；需要实机状态时使用 `submit` 和 `receipt`。

完整协议、限制和 Cargo 依赖替换示例见 [调度台接入说明](../../docs/guides/protocol.md)。

## Rust

已有 SDK 应用可以把 Cargo 中原来的路径依赖替换为：

```toml
zectrix-sdk = { package = "screen-scheduler-client", path = "../screen-scheduler/clients/screen-scheduler-client" }
```

上面的路径以调用方项目与 `screen-scheduler` 同级为例，请按实际克隆位置调整。

保留常用 `use zectrix_sdk::{Device, OpenOptions, ImageFormat, Event}` 和原图像/按键调用代码。目标地址改成 `http://127.0.0.1:38477`，设置环境变量 `SCREEN_SCHEDULER_KEY`（从管理界面复制），或改用 `Device::open_with_key(options, key)`。底层设备 palette/status/音频方法并未全部移植，使用这些方法的程序需单独适配。

`submit_with_sequence` 可按原序号重试不确定的提交；`last_sequence` 可获取最后分配序号。重试必须使用完全相同的 PNG 和格式。请求失败时不自动改序号重发。

```powershell
cargo build --examples
# 先启动调度台；将实际接入密钥设置到环境变量中。
cargo run --example show -- http://127.0.0.1:38477 picture.png
```

示例 `original_sdk` 直接使用未修改的原 SDK，可用于验证“仅改地址”的 UDP 接入；`http_roundtrip` 验证 HTTP 按键与显示回执。

## Python

`python/screen_scheduler.py` 只使用 Python 标准库。将它加入原生图程序的模块路径，然后使用 `Device.open(OpenOptions(...))`、`show_with_format`、`next_event(timeout=...)`、`close`。提供同名环境变量或 `api_key=` 参数。可以使用 `with` 管理真正的程序生命周期；不要每生成一张图片就退出来源。

应用本身仍负责数据采集和画面生成，客户端负责来源注册、图像提交、心跳、按键接收和退出。关闭来源后，调度器会立即清除该来源的任务，不承诺继续展示。
