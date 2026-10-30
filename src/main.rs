#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]
use axum::{
    body::Bytes,
    extract::{DefaultBodyLimit, Path, State},
    http::{header, HeaderMap, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use note4_screen_scheduler::scheduler::*;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, Notify};
use zectrix_sdk::{Device, Event, ImageFormat, OpenOptions};
mod audio;
mod diagnostics;
mod builtin_plugins;
mod ingress;
mod migration;
mod runtime;
#[cfg(windows)]
mod tray;
mod plugins;

type ApiResult = Result<Json<Value>, (StatusCode, String)>;
fn bad(e: impl ToString) -> (StatusCode, String) {
    (StatusCode::BAD_REQUEST, e.to_string())
}
#[derive(Clone, Serialize, Deserialize)]
struct ReconnectSettings {
    enabled: bool,
    window_seconds: u64,
    interval_seconds: u64,
}
impl Default for ReconnectSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            window_seconds: 120,
            interval_seconds: 5,
        }
    }
}
#[derive(Serialize, Deserialize, Default)]
struct Saved {
    target: String,
    preempt: bool,
    #[serde(default)]
    reconnect: ReconnectSettings,
    #[serde(default)]
    api_key: String,
}
struct Inner {
    scheduler: Scheduler,
    images: HashMap<String, Vec<u8>>,
    device: Option<Arc<Device>>,
    generation: u64,
    mode: String,
    target: String,
    health: String,
    blocked: bool,
    connecting: bool,
    reconnect: ReconnectSettings,
    reconnect_until: Option<u64>,
    reconnect_next: u64,
    reconnect_epoch: u64,
    reconnect_blocked: bool,
    sending: bool,
    display: Vec<u8>,
    logs: Vec<Value>,
    keys: HashMap<String, Vec<Value>>,
    external: HashMap<String, ingress::Session>,
    in_flight: Option<Frame>,
    focus_unknown: bool,
    recording: bool,
    media_epoch: u64,
    audio_pending: Vec<audio::Pending>,
    audio_status: Value,
}
struct App {
    inner: Mutex<Inner>,
    device_operation: Mutex<()>,
    start: Instant,
    token: String,
    config: PathBuf,
    shutdown: Notify,
    api_key: String,
    http_address: String,
    sdk_address: String,
    plugins: Mutex<plugins::Manager>,
    plugin_operation: Mutex<()>,
}
impl App {
    fn now(&self) -> u64 {
        self.start.elapsed().as_millis() as u64
    }
    async fn save(&self) {
        let i = self.inner.lock().await;
        let saved = Saved {
            target: i.target.clone(),
            preempt: i.scheduler.preempt,
            reconnect: i.reconnect.clone(),
            api_key: self.api_key.clone(),
        };
        if let Ok(bytes) = serde_json::to_vec_pretty(&saved) {
            if let Err(e) = std::fs::write(&self.config, bytes) {
                eprintln!("配置保存失败: {e}");
            }
        }
    }
}
fn log(i: &mut Inner, now: u64, message: impl Into<String>) {
    let message = message.into();
    diagnostics::record(now, &message, &format!(
        "target={} generation={} sending={} recording={} blocked={} reconnect={}",
        i.target, i.generation, i.sending, i.recording, i.blocked, i.reconnect.enabled,
    ));
    i.logs.insert(0, json!({"at":now,"message":message}));
    i.logs.truncate(80);
}
fn auth(a: &App, h: &HeaderMap) -> Result<(), (StatusCode, String)> {
    if h.get("x-control-token").and_then(|v| v.to_str().ok()) == Some(&a.token) {
        Ok(())
    } else {
        Err((StatusCode::FORBIDDEN, "请从本机管理页面操作".into()))
    }
}
async fn state(State(a): State<Arc<App>>) -> Json<Value> {
    let plugin_snapshot = a.plugins.lock().await.snapshot();
    let i = a.inner.lock().await;
    let now = a.now();
    let sources:Vec<_>=i.scheduler.sources.iter().map(|s|json!({"config":s,"effective":s.effective(now),"reason":i.scheduler.reason(&s.id,now),"keys":i.keys.get(&s.id)})).collect();
    Json(
        json!({"application":{"packaged":runtime::layout().packaged(),"autostart_supported":runtime::autostart_supported(),"autostart":runtime::autostart_enabled()},"now":now,"token":a.token,"plugins":plugin_snapshot,"sources":sources,"queue":ingress::queue(&i,now),"access":{"http":a.http_address,"sdk":a.sdk_address,"api_key":a.api_key,"mode":"managed_acceptance"},"external":ingress::summaries(&i),"current":i.scheduler.current,"preempt":i.scheduler.preempt,"paused":i.scheduler.paused,"device":{"mode":i.mode,"target":i.target,"health":i.health,"connected":i.device.is_some(),"blocked":i.blocked,"sending":i.sending,"connecting":i.connecting,"reconnect":i.reconnect,"reconnect_until":i.reconnect_until,"recording":i.recording,"audio":i.audio_status},"logs":i.logs}),
    )
}
async fn screen(State(a): State<Arc<App>>) -> Response {
    let i = a.inner.lock().await;
    png(i.display.clone())
}
fn png(bytes: Vec<u8>) -> Response {
    if bytes.is_empty() {
        return StatusCode::NOT_FOUND.into_response();
    }
    (
        [
            (header::CONTENT_TYPE, "image/png"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        bytes,
    )
        .into_response()
}
async fn source_image(State(a): State<Arc<App>>, Path(id): Path<String>) -> Response {
    png(a
        .inner
        .lock()
        .await
        .images
        .get(&id)
        .cloned()
        .unwrap_or_default())
}
#[derive(Deserialize)]
struct Command {
    op: String,
    #[serde(default)]
    id: String,
    #[serde(default)]
    data: Value,
}
fn number(v: &Value, key: &str, default: u64) -> u64 {
    v[key].as_u64().unwrap_or(default)
}
fn text<'a>(v: &'a Value, key: &str, default: &'a str) -> &'a str {
    v[key].as_str().unwrap_or(default)
}
fn boolean(v: &Value, key: &str, default: bool) -> bool {
    v[key].as_bool().unwrap_or(default)
}
fn apply_settings(s: &mut Source, v: &Value) -> Result<(), String> {
    let priority = number(v, "priority", s.priority as u64);
    if !(1..=5).contains(&priority) {
        return Err("优先级应为 1～5".into());
    }
    s.priority = priority as u8;
    s.name = text(v, "name", &s.name).trim().to_string();
    if s.name.is_empty() || s.name.len() > 120 {
        return Err("请输入不超过 40 个汉字的来源名称".into());
    }
    s.min_ms = number(v, "min_ms", s.min_ms).min(86400000);
    s.hold_ms = number(v, "hold_ms", s.hold_ms).min(604800000);
    s.ttl_ms = number(v, "ttl_ms", s.ttl_ms).min(604800000);
    s.persistent = boolean(v, "persistent", s.persistent);
    s.bypass = boolean(v, "bypass", s.bypass);
    s.enabled = boolean(v, "enabled", s.enabled);
    s.format = text(v, "format", &s.format).to_string();
    // Legacy fit is retained only for migration; plugins own image sizing.
    if !["mono", "gray4", "gray16"].contains(&s.format.as_str()) {
        return Err("画面格式不正确".into());
    }
    Ok(())
}
async fn command(State(a): State<Arc<App>>, h: HeaderMap, Json(c): Json<Command>) -> ApiResult {
    auth(&a, &h)?;
    let now = a.now();
    match c.op.as_str() {
        "application_settings" => {
            runtime::set_autostart(boolean(&c.data, "autostart", false)).map_err(bad)?;
        }
        "stop" => {
            a.inner.lock().await.scheduler.paused = true;
            a.shutdown.notify_one();
        }
        "connect" => {
            {
                let mut i = a.inner.lock().await;
                i.reconnect_epoch += 1;
                i.reconnect_until = None;
            }
            connect(a.clone(), text(&c.data, "target", "").trim().into(), None).await?;
        }
        "reconnect_settings" => {
            let window = number(&c.data, "window_seconds", 120);
            let interval = number(&c.data, "interval_seconds", 5);
            if !(1..=86400).contains(&window) || !(1..=3600).contains(&interval) {
                return Err(bad("重试时限应为 1～86400 秒，间隔应为 1～3600 秒"));
            }
            let mut i = a.inner.lock().await;
            i.reconnect = ReconnectSettings {
                enabled: boolean(&c.data, "enabled", false),
                window_seconds: window,
                interval_seconds: interval,
            };
            i.reconnect_epoch += 1;
            i.reconnect_until = None;
        }
        "mode" => {
            let _operation = a.device_operation.lock().await;
            let mut i = a.inner.lock().await;
            if i.sending || i.connecting {
                return Err(bad("请等待正在进行的设备操作完成"));
            }
            i.reconnect_epoch += 1;
            i.reconnect_until = None;
            let device = i.device.take();
            i.generation += 1;
            i.media_epoch += 1;
            i.audio_pending.clear();
            i.recording = false;
            i.mode = text(&c.data, "mode", "simulation").into();
            if !["simulation", "device"].contains(&i.mode.as_str()) {
                i.mode = "simulation".into();
            }
            i.blocked = false;
            i.scheduler.current = None;
            i.display.clear();
            i.focus_unknown = false;
            i.health = if i.mode == "simulation" {
                "模拟屏幕，不发送到设备"
            } else {
                "尚未连接设备"
            }
            .into();
            drop(i);
            if let Some(d) = device {
                let _ = d.close().await;
            }
        }
        "disconnect" => {
            {
                let mut i = a.inner.lock().await;
                i.reconnect_epoch += 1;
                i.reconnect_until = None;
            }
            let _operation = a.device_operation.lock().await;
            let mut i = a.inner.lock().await;
            if i.sending || i.connecting {
                return Err(bad("请等待当前操作完成后再断开"));
            }
            let d = i.device.take();
            i.generation += 1;
            i.media_epoch += 1;
            i.audio_pending.clear();
            i.recording = false;
            i.scheduler.current = None;
            i.health = "已断开，需手动连接".into();
            log(&mut i, now, "用户主动断开设备，取消自动重连");
            drop(i);
            if let Some(d) = d {
                let _ = d.close().await;
            }
        }
        "global" => {
            let mut i = a.inner.lock().await;
            i.scheduler.preempt = boolean(&c.data, "preempt", true);
            let paused = boolean(&c.data, "paused", false);
            if paused != i.scheduler.paused {
                i.media_epoch += 1;
            }
            i.scheduler.paused = paused;
            if i.scheduler.paused {
                i.audio_pending.clear();
            }
        }
        "add" => {
            let id = uuid::Uuid::new_v4().to_string();
            let mut s = Source::new(id.clone(), "新内容来源".into(), 3);
            apply_settings(&mut s, &c.data).map_err(bad)?;
            a.inner.lock().await.scheduler.add(s);
            return Ok(Json(json!({"id":id})));
        }
        "settings" => {
            let mut i = a.inner.lock().await;
            let mut s = i
                .scheduler
                .source(&c.id)
                .cloned()
                .ok_or_else(|| bad("来源不存在"))?;
            apply_settings(&mut s, &c.data).map_err(bad)?;
            if !s.enabled {
                i.audio_pending.retain(|p| p.source != c.id);
            }
            if c.data.get("format").is_some() {
                s.format_override = true;
            }
            *i.scheduler.source_mut(&c.id).unwrap() = s;
            drop(i);
            plugins::save_source(&a, &c.id).await;
        }
        "remove" => {
            let owner = a.plugins.lock().await.owner(&c.id);
            if let Some(id) = owner {
                if a.plugins.lock().await.is_channel(&c.id) {
                    return Err(bad(
                        "该通道由插件管理，请在插件主页移除来源，或在显示规则中禁用通道",
                    ));
                }
                plugins::set_enabled(a.clone(), &id, false)
                    .await
                    .map_err(bad)?;
                return Ok(Json(json!({"ok":true})));
            }
            let mut i = a.inner.lock().await;
            i.scheduler.remove(&c.id);
            i.images.remove(&c.id);
            i.keys.remove(&c.id);
            i.external.remove(&c.id);
            log(&mut i, now, "来源已退出，已清除其任务");
        }
        "boost" => {
            let mut i = a.inner.lock().await;
            let s = i
                .scheduler
                .source_mut(&c.id)
                .ok_or_else(|| bad("来源不存在"))?;
            let p = number(&c.data, "priority", 1);
            if !(1..=5).contains(&p) {
                return Err(bad("优先级应为 1～5"));
            }
            s.boost = if boolean(&c.data, "clear", false) {
                None
            } else {
                Some(Boost {
                    priority: p as u8,
                    until: match number(&c.data, "duration_ms", 300000) {
                        0 => None,
                        n => Some(now + n.min(604800000)),
                    },
                    until_replaced: boolean(&c.data, "until_replaced", false),
                })
            };
        }
        "key" => {
            key(a.clone(), text(&c.data, "key", "Confirm"), "Short").await;
        }
        "retry" => {
            let mut i = a.inner.lock().await;
            i.blocked = false;
            log(&mut i, now, "用户明确允许继续发送；未知结果可能曾显示");
        }
        _ => return Err(bad("未知操作")),
    }
    a.save().await;
    Ok(Json(json!({"ok":true})))
}
async fn upload(
    State(a): State<Arc<App>>,
    Path(id): Path<String>,
    h: HeaderMap,
    bytes: Bytes,
) -> ApiResult {
    auth(&a, &h)?;
    // Browser normalizes all chosen ordinary images to a bounded PNG.
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(bad("图片不得超过 8 MiB"));
    }
    let data = bytes.to_vec();
    let mut reader =
        image::ImageReader::with_format(std::io::Cursor::new(&data), image::ImageFormat::Png);
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(400);
    limits.max_image_height = Some(300);
    limits.max_alloc = Some(8 * 1024 * 1024);
    reader.limits(limits);
    let decoded = reader.decode().map_err(bad)?;
    if decoded.width() != 400 || decoded.height() != 300 {
        return Err(bad("管理界面应提交 400×300 PNG"));
    }
    let mut i = a.inner.lock().await;
    i.scheduler.update(&id, a.now()).map_err(bad)?;
    i.images.insert(id, data);
    Ok(Json(json!({"ok":true})))
}
async fn connect(
    a: Arc<App>,
    target: String,
    retry_epoch: Option<u64>,
) -> Result<(), (StatusCode, String)> {
    let _operation = a.device_operation.lock().await;
    if target.parse::<std::net::Ipv4Addr>().is_err()
        && target.parse::<std::net::SocketAddrV4>().is_err()
        && !(target.len() == 12 && target.bytes().all(|c| c.is_ascii_hexdigit()))
    {
        return Err(bad("请输入设备 IP、IP:端口或 12 位设备 ID"));
    }
    let generation;
    {
        let mut i = a.inner.lock().await;
        if retry_epoch.is_some_and(|e| {
            e != i.reconnect_epoch
                || i.reconnect_until.is_none_or(|until| a.now() >= until)
                || i.mode != "device"
        }) {
            return Err(bad("重连已取消或超时"));
        }
        if i.sending || i.connecting || i.device.is_some() {
            return Err(bad("请先完成当前操作并断开已有连接"));
        }
        i.audio_pending.clear();
        i.recording = false;
        i.connecting = true;
        i.mode = "device".into();
        i.target = target.clone();
        i.health = "正在连接指定设备…".into();
        i.generation += 1;
        i.media_epoch += 1;
        generation = i.generation;
        log(&mut i, a.now(), if retry_epoch.is_some() { "开始自动重连" } else { "开始手动连接" });
    }
    let result = Device::open(OpenOptions {
        target: Some(target),
        client_name: Some("墨枢".into()),
    })
    .await;
    let mut i = a.inner.lock().await;
    i.connecting = false;
    if retry_epoch.is_some_and(|e| {
        e != i.reconnect_epoch
            || i.reconnect_until.is_none_or(|until| a.now() >= until)
            || i.mode != "device"
    }) {
        drop(i);
        if let Ok(device) = result {
            let _ = device.close().await;
        }
        return Err(bad("重连已取消或超时"));
    }
    match result {
        Ok(device) => {
            let d = Arc::new(device);
            i.device = Some(d.clone());
            i.health = "设备已连接，等待调度画面".into();
            i.reconnect_until = None;
            i.blocked = retry_epoch.is_some() && (i.reconnect_blocked || i.focus_unknown);
            i.scheduler.current = None;
            log(&mut i, a.now(), "已取得指定设备的连接");
            drop(i);
            tokio::spawn(events(a.clone(), d, generation));
            Ok(())
        }
        Err(e) => {
            i.health = format!("连接失败：{e}");
            log(&mut i, a.now(), format!("连接失败：{e}"));
            Err(bad(e))
        }
    }
}
async fn events(a: Arc<App>, d: Arc<Device>, generation: u64) {
    loop {
        match d.next_event().await {
            Ok(Some(Event::Key { key: k, action })) => {
                if a.inner.lock().await.generation == generation {
                    key(a.clone(), &format!("{k:?}"), &format!("{action:?}")).await;
                }
            }
            Ok(Some(Event::Disconnected { reason })) => {
                let mut i = a.inner.lock().await;
                if i.generation == generation {
                    let message = format!("设备已断开：{reason:?}；sending={} recording={}", i.sending, i.recording);
                    log(&mut i, a.now(), message);
                    i.reconnect_blocked = i.blocked || i.focus_unknown;
                    i.device = None;
                    i.audio_pending.clear();
                    i.media_epoch += 1;
                    i.recording = false;
                    i.health = format!("设备已断开：{reason:?}");
                    if i.reconnect.enabled {
                        i.reconnect_until = Some(a.now() + i.reconnect.window_seconds * 1000);
                        i.reconnect_next = a.now() + i.reconnect.interval_seconds * 1000;
                    }
                    i.blocked = true;
                }
                break;
            }
            Ok(Some(Event::RecordingStarted)) => {
                let mut i = a.inner.lock().await;
                if i.generation == generation {
                    i.media_epoch += 1;
                    i.recording = true;
                    i.audio_pending.clear();
                    log(
                        &mut i,
                        a.now(),
                        "设备开始录音，暂停媒体；录音不会保存或上传",
                    );
                }
                // The SDK marks active playback Interrupted when capture begins.
                // Do not call stop(): it would stop the user's recording first.
            }
            Ok(Some(Event::RecordingFinished { .. })) => {
                let mut i = a.inner.lock().await;
                if i.generation == generation {
                    i.media_epoch += 1;
                    i.recording = false;
                    log(&mut i, a.now(), "录音结束，继续调度");
                }
            }
            Ok(None) => {
                let mut i = a.inner.lock().await;
                if i.generation == generation { log(&mut i, a.now(), "设备事件流结束（未提供断开原因）"); }
                break;
            },
            Err(e) => {
                let mut i = a.inner.lock().await;
                if i.generation == generation {
                    log(&mut i, a.now(), format!("事件连接结束：{e}"));
                    i.reconnect_blocked = i.blocked || i.focus_unknown;
                    i.device = None;
                    i.audio_pending.clear();
                    i.media_epoch += 1;
                    i.recording = false;
                    i.blocked = true;
                    i.health = format!("事件连接结束：{e}");
                }
                break;
            }
        }
    }
}
async fn key(a: Arc<App>, k: &str, action: &str) {
    let now = a.now();
    let mut i = a.inner.lock().await;
    // A refresh in progress has no reliable physical key focus. Do not misroute it.
    if i.sending || i.focus_unknown {
        log(
            &mut i,
            now,
            "正在换图或显示结果未知，忽略按键以免发给错误来源",
        );
        return;
    }
    let Some(id) = i.scheduler.key_target(now) else {
        log(&mut i, now, "当前没有有效任务接收按键");
        return;
    };
    let name = i.scheduler.source(&id).unwrap().name.clone();
    let shown_revision = i.scheduler.current.as_ref().unwrap().frame.revision;
    if let Some(session) = i.external.get_mut(&id) {
        session.push_key(k, action, shown_revision, now);
    }
    i.keys
        .entry(id.clone())
        .or_default()
        .push(json!({"key":k,"action":action,"at":now}));
    if let Some(q) = i.keys.get_mut(&id) {
        if q.len() > 30 {
            q.remove(0);
        }
    }
    log(&mut i, now, format!("按键 {k} → {name}（交给当前来源）"));
    drop(i);
    plugins::key(&a, &id, k, action, shown_revision).await;
}

async fn run_scheduler(a: Arc<App>) {
    let mut tick = tokio::time::interval(Duration::from_millis(200));
    loop {
        tick.tick().await;
        let _operation = a.device_operation.lock().await;
        let job = {
            let mut i = a.inner.lock().await;
            if i.blocked || i.sending || i.recording || (i.mode == "device" && i.device.is_none()) {
                None
            } else {
                let now = a.now();
                if let Some(frame) = i.scheduler.next(now) {
                    if let Some(bytes) = i.images.get(&frame.id).cloned() {
                        let format = i.scheduler.source(&frame.id).unwrap().format.clone();
                        // A sound already attached to the departing display must never replay.
                        if let Some(old) = i.scheduler.current.as_ref().map(|d| d.frame.id.clone())
                        {
                            if old != frame.id {
                                i.audio_pending.retain(|p| p.source != old);
                            }
                        }
                        i.sending = true;
                        i.in_flight = Some(frame.clone());
                        ingress::mark(&mut i, &frame, "displaying", None);
                        Some((frame, bytes, format, i.device.clone(), i.generation))
                    } else {
                        None
                    }
                } else {
                    None
                }
            }
        };
        if let Some((frame, bytes, format, device, generation)) = job {
            let result = if let Some(d) = device {
                d.show_with_format(
                    &bytes,
                    match format.as_str() {
                        "gray4" => ImageFormat::Gray4,
                        "gray16" => ImageFormat::Gray16,
                        _ => ImageFormat::Mono,
                    },
                )
                .await
            } else {
                tokio::time::sleep(Duration::from_millis(150)).await;
                Ok(())
            };
            let mut i = a.inner.lock().await;
            i.sending = false;
            i.in_flight = None;
            if generation != i.generation {
                continue;
            }
            let completed = result.is_ok();
            match result {
                Ok(()) => {
                    i.focus_unknown = false;
                    let outcome = if i.mode == "simulation" {
                        "simulated"
                    } else {
                        "displayed"
                    };
                    ingress::mark(&mut i, &frame, outcome, None);
                    i.display = bytes;
                    i.scheduler.complete(frame.clone(), a.now());
                    i.health = if i.mode == "simulation" {
                        "模拟显示完成（非实机回执）"
                    } else {
                        "设备已报告显示完成"
                    }
                    .into();
                    let name = i
                        .scheduler
                        .source(&frame.id)
                        .map(|s| s.name.clone())
                        .unwrap_or("已退出来源".into());
                    log(&mut i, a.now(), format!("显示完成：{name}"));
                }
                Err(e) => {
                    if matches!(e, zectrix_sdk::Error::ResultUnknown) {
                        i.focus_unknown = true;
                    }
                    let outcome = if matches!(e, zectrix_sdk::Error::ResultUnknown) {
                        "result_unknown"
                    } else {
                        "failed"
                    };
                    ingress::mark(&mut i, &frame, outcome, Some(e.to_string()));
                    i.blocked = true;
                    i.audio_pending.clear();
                    i.health = format!("发送暂停：{e}");
                    log(&mut i, a.now(), format!("未自动重发：{e}"));
                }
            }
            drop(i);
            if completed {
                plugins::displayed(&a, &frame).await;
            }
        }
        drop(_operation);
        {
            let mut i = a.inner.lock().await;
            let now = a.now();
            let sources = i.scheduler.sources.clone();
            i.audio_pending.retain(|p| {
                sources
                    .iter()
                    .any(|s| s.id == p.source && s.valid(now) && s.revision == p.revision)
            });
        }
        audio::send(&a).await;
    }
}
async fn guard(req: axum::extract::Request, next: axum::middleware::Next) -> Response {
    let plugin_page = req.uri().path().starts_with("/control/plugin-ui/");
    let host = req
        .headers()
        .get(header::HOST)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if !(host.starts_with("127.0.0.1:") || host.starts_with("localhost:")) {
        return StatusCode::FORBIDDEN.into_response();
    }
    let mut r = next.run(req).await;
    r.headers_mut()
        .insert(header::CACHE_CONTROL, "no-store".parse().unwrap());
    r.headers_mut()
        .insert("x-content-type-options", "nosniff".parse().unwrap());
    r.headers_mut().insert("content-security-policy",if plugin_page{"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; frame-ancestors 'self'"}else{"default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'"}.parse().unwrap());
    r
}
#[tokio::main]
async fn main() {
    if let Err(error) = run().await { runtime::report_error(&error.to_string()); std::process::exit(1); }
}
async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let requested_port = std::env::args().skip_while(|s|s!="--port").nth(1).unwrap_or("38476".into()).parse::<u16>()?;
    if runtime::wants_tray() && runtime::existing_instance(requested_port).await {
        if !runtime::flag("--autostart") { runtime::open_browser(&format!("http://127.0.0.1:{requested_port}")); }
        return Ok(());
    }
    let http_address = std::env::args()
        .skip_while(|s| s != "--http-bind")
        .nth(1)
        .unwrap_or("127.0.0.1:38477".into());
    let sdk_address = std::env::args()
        .skip_while(|s| s != "--sdk-bind")
        .nth(1)
        .unwrap_or("127.0.0.1:32342".into());
    let http_listener = tokio::net::TcpListener::bind(&http_address).await?;
    let sdk_socket = Arc::new(tokio::net::UdpSocket::bind(&sdk_address).await?);
    let http_address = http_listener.local_addr()?.to_string();
    let sdk_address = sdk_socket.local_addr()?.to_string();
    let config = std::env::args()
        .skip_while(|s| s != "--config")
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(||runtime::layout().config());
    if let Some(parent)=config.parent().filter(|p|!p.as_os_str().is_empty()) { std::fs::create_dir_all(parent)?; }
    diagnostics::init(&config)?;
    migration::legacy_gallery(&config)
        .await
        .map_err(std::io::Error::other)?;
    builtin_plugins::install_once(&config.with_extension("plugins"))
        .await
        .map_err(std::io::Error::other)?;
    let plugin_manager =
        plugins::Manager::load(config.with_extension("plugins")).map_err(std::io::Error::other)?;
    let saved: Saved = std::fs::read(&config)
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or(Saved {
            preempt: true,
            ..Default::default()
        });
    let mut scheduler = Scheduler::default();
    scheduler.preempt = saved.preempt;
    let a = Arc::new(App {
        inner: Mutex::new(Inner {
            scheduler,
            images: HashMap::new(),
            device: None,
            generation: 0,
            mode: "simulation".into(),
            target: saved.target,
            health: "模拟屏幕，不发送到设备".into(),
            blocked: false,
            connecting: false,
            reconnect: saved.reconnect,
            reconnect_until: None,
            reconnect_next: 0,
            reconnect_epoch: 0,
            reconnect_blocked: false,
            sending: false,
            display: vec![],
            logs: vec![],
            keys: HashMap::new(),
            external: HashMap::new(),
            in_flight: None,
            focus_unknown: false,
            recording: false,
            media_epoch: 0,
            audio_pending: vec![],
            audio_status: json!({"status":"idle"}),
        }),
        device_operation: Mutex::new(()),
        start: Instant::now(),
        token: uuid::Uuid::new_v4().to_string(),
        config,
        shutdown: Notify::new(),
        api_key: if saved.api_key.is_empty() {
            uuid::Uuid::new_v4().to_string()
        } else {
            saved.api_key
        },
        http_address,
        sdk_address,
        plugins: Mutex::new(plugin_manager),
        plugin_operation: Mutex::new(()),
    });
    tokio::spawn(run_scheduler(a.clone()));
    tokio::spawn(reconnect_loop(a.clone()));
    plugins::initialize(a.clone()).await;
    let leases = a.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_millis(200));
        loop {
            tick.tick().await;
            ingress::expire(&leases).await;
        }
    });
    a.save().await;
    let ingress_app = a.clone();
    tokio::spawn(async move {
        if let Err(e) = axum::serve(http_listener, ingress::router(ingress_app)).await {
            eprintln!("HTTP ingress stopped: {e}");
        }
    });
    tokio::spawn(ingress::udp(a.clone(), sdk_socket));
    let app = Router::new()
        .route(
            "/",
            get(|| async { Html(include_str!("../web/index.html")) }),
        )
        .route(
            "/app.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../web/app.js"),
                )
            }),
        )
        .route(
            "/style.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css")],
                    include_str!("../web/style.css"),
                )
            }),
        )
        .route("/controls.js", get(|| async { ([(header::CONTENT_TYPE, "text/javascript")], include_str!("../web/controls.js")) }))
        .route("/control/state", get(state))
        .route(
            "/plugins.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../web/plugins.js"),
                )
            }),
        )
        .route("/control/command", post(command))
        .route("/control/screen.png", get(screen))
        .route("/control/image/{id}", get(source_image).post(upload))
        .route("/control/plugins/install", post(plugins::install))
        .route("/control/plugins/{id}", post(plugins::control))
        .route("/control/plugins/{id}/export", get(plugins::export))
        .route("/control/plugin-ui/{id}", get(plugins::page))
        .layer(DefaultBodyLimit::max(10 * 1024 * 1024))
        .layer(axum::middleware::from_fn(guard))
        .with_state(a.clone());
    let port = std::env::args()
        .skip_while(|s| s != "--port")
        .nth(1)
        .unwrap_or("38476".into())
        .parse::<u16>()?;
    let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port)).await?;
    println!(
        "墨枢 http://127.0.0.1:{}",
        listener.local_addr()?.port()
    );
    let url = format!("http://127.0.0.1:{}", listener.local_addr()?.port());
    #[cfg(windows)]
    let _tray = if runtime::wants_tray() {
        let status=Arc::new(std::sync::Mutex::new(String::from("墨枢 · 启动中")));
        let (sender,mut receiver)=tokio::sync::mpsc::unbounded_channel();
        let handle=tray::Tray::start(status.clone(),sender,&runtime::layout().root.join("assets/InkHub.ico")).map_err(std::io::Error::other)?;
        let tray_app=a.clone();let tray_url=url.clone();
        tokio::spawn(async move {
            let mut tick=tokio::time::interval(Duration::from_secs(1));
            loop { tokio::select! {
                _=tick.tick()=>{ let inner=tray_app.inner.lock().await; if let Ok(mut value)=status.lock() { *value=format!("墨枢 · {}",inner.health); } },
                action=receiver.recv()=>match action {
                    Some(tray::Command::Open)=>runtime::open_browser(&tray_url),
                    Some(tray::Command::Exit)=>{tray_app.shutdown.notify_one();break},
                    None=>break,
                }
            }}
        });
        Some(handle)
    } else { None };
    if runtime::wants_browser() { runtime::open_browser(&url); }
    axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            tokio::select! {_=tokio::signal::ctrl_c()=>{},_=a.shutdown.notified()=>{}}
            {
                let mut inner=a.inner.lock().await;
                inner.scheduler.paused=true;
                inner.reconnect.enabled=false;
                inner.reconnect_until=None;
                inner.reconnect_epoch+=1;
            }
            plugins::shutdown(&a).await;
            let _operation=a.device_operation.lock().await;
            let d = { let mut inner=a.inner.lock().await;inner.generation+=1;inner.device.take() };
            if let Some(d) = d {
                let _ = d.close().await;
            }
        })
        .await?;
    Ok(())
}

async fn reconnect_loop(a: Arc<App>) {
    let mut tick = tokio::time::interval(Duration::from_millis(200));
    loop {
        tick.tick().await;
        let pending = {
            let mut i = a.inner.lock().await;
            if let Some(until) = i.reconnect_until {
                if a.now() >= until {
                    i.reconnect_until = None;
                    i.health = "自动重连时限已结束，可手动连接".into();
                    log(&mut i, a.now(), "自动重连时限已结束");
                    None
                } else if i.reconnect.enabled
                    && i.mode == "device"
                    && i.device.is_none()
                    && !i.connecting
                    && !i.sending
                    && a.now() >= i.reconnect_next
                {
                    i.reconnect_next = a.now() + i.reconnect.interval_seconds * 1000;
                    Some((i.target.clone(), i.reconnect_epoch, until - a.now()))
                } else {
                    None
                }
            } else {
                None
            }
        };
        if let Some((target, epoch, remaining)) = pending {
            // Drop an in-flight open at the retry-window boundary. Manual disconnect invalidates its epoch.
            let result = tokio::time::timeout(
                Duration::from_millis(remaining),
                connect(a.clone(), target, Some(epoch)),
            )
            .await;
            let mut i = a.inner.lock().await;
            if result.is_err() {
                i.connecting = false;
                i.reconnect_until = None;
                i.health = "自动重连时限已结束，可手动连接".into();
                log(&mut i, a.now(), "自动重连尝试超时，重连窗口已结束");
            }
            if i.reconnect_until.is_some() {
                i.reconnect_next = a.now() + i.reconnect.interval_seconds * 1000;
            }
        }
    }
}
