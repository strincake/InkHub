//! Trusted local Python plugins. Worker isolation is a reliability boundary, not a security sandbox.
use super::*;
use std::collections::{BTreeMap, VecDeque};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    sync::Semaphore,
};

#[derive(Clone, Serialize, Deserialize)]
struct Disk {
    enabled: bool,
    settings: Value,
    state: Value,
    source: Source,
    #[serde(default)]
    channels: BTreeMap<String, Source>,
}
pub struct Plugin {
    manifest: Value,
    disk: Disk,
    source: Option<String>,
    channels: BTreeMap<String, String>,
    events: VecDeque<Value>,
    running: bool,
    epoch: u64,
    next_at: Option<u64>,
    cancel: Arc<Notify>,
    status: String,
    error: Option<String>,
    last_run: Option<u64>,
    last_log: String,
}
pub struct Manager {
    root: PathBuf,
    items: BTreeMap<String, Plugin>,
    slots: Arc<Semaphore>,
    stopping: bool,
}
fn slug(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 48
        && s.as_bytes()[0].is_ascii_lowercase()
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}
impl Manager {
    pub fn load(root: PathBuf) -> Result<Self, String> {
        for sub in ["packages", "data", "runs"] {
            std::fs::create_dir_all(root.join(sub)).map_err(|e| e.to_string())?;
        }
        let root = root.canonicalize().map_err(|e| e.to_string())?;
        let mut items = BTreeMap::new();
        for e in std::fs::read_dir(root.join("packages"))
            .map_err(|e| e.to_string())?
            .flatten()
        {
            let id = e.file_name().to_string_lossy().to_string();
            if !slug(&id) {
                continue;
            }
            let Ok(bytes) = std::fs::read(e.path().join("plugin.json")) else {
                continue;
            };
            let Ok(manifest) = serde_json::from_slice::<Value>(&bytes) else {
                continue;
            };
            if manifest["id"] != id || manifest["api_version"] != 1 {
                continue;
            }
            let saved = std::fs::read(root.join("data").join(&id).join("record.json"))
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok());
            let mut p = Plugin::new(manifest, saved);
            p.status = if p.disk.enabled {
                "等待启动"
            } else {
                "已禁用"
            }
            .into();
            items.insert(id, p);
        }
        Ok(Self {
            root,
            items,
            slots: Arc::new(Semaphore::new(4)),
            stopping: false,
        })
    }
    pub fn snapshot(&self) -> Value {
        json!(self.items.iter().map(|(id,p)|json!({"id":id,"manifest":p.manifest,"enabled":p.disk.enabled,"settings":p.disk.settings,"state":p.disk.state,"source":if p.manifest["multi_channel"]==true {None}else{p.source.clone()},"channels":p.channels,"status":p.status,"error":p.error,"running":p.running,"last_run":p.last_run,"last_log":p.last_log,"pending":p.events.len(),"next_at":p.next_at})).collect::<Vec<_>>())
    }
    fn save(&self, id: &str) -> Result<(), String> {
        let p = self.items.get(id).ok_or("插件不存在")?;
        let folder = self.root.join("data").join(id);
        std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        let bytes = serde_json::to_vec_pretty(&p.disk).map_err(|e| e.to_string())?;
        let temp = folder.join("record.tmp");
        std::fs::write(&temp, bytes).map_err(|e| e.to_string())?;
        std::fs::rename(temp, folder.join("record.json")).map_err(|e| e.to_string())
    }
    pub fn is_channel(&self, source: &str) -> bool {
        self.items
            .values()
            .any(|p| p.channels.values().any(|id| id == source))
    }
    pub fn owner(&self, source: &str) -> Option<String> {
        self.items
            .iter()
            .find(|(_, p)| {
                p.source.as_deref() == Some(source) || p.channels.values().any(|s| s == source)
            })
            .map(|(id, _)| id.clone())
    }
    pub fn enqueue(&mut self, id: &str, event: Value) -> Result<(), String> {
        let p = self.items.get_mut(id).ok_or("插件不存在")?;
        if !p.disk.enabled {
            return Err("请先启用插件".into());
        }
        if event["type"] == "interval" && p.events.iter().any(|e| e["type"] == "interval") {
            return Ok(());
        }
        if p.events.len() >= 32 {
            return Err("插件事件积压，请稍后再试".into());
        }
        p.events.push_back(event);
        Ok(())
    }
}
impl Plugin {
    fn new(manifest: Value, saved: Option<Disk>) -> Self {
        let settings = manifest["settings"]
            .as_array()
            .map(|fields| {
                fields
                    .iter()
                    .map(|f| {
                        (
                            f["key"].as_str().unwrap_or_default().into(),
                            f.get("default")
                                .cloned()
                                .unwrap_or(match f["type"].as_str() {
                                    Some("number") => json!(0),
                                    Some("boolean") => json!(false),
                                    Some("select") => f["options"][0].clone(),
                                    _ => json!(""),
                                }),
                        )
                    })
                    .collect::<serde_json::Map<_, _>>()
            })
            .unwrap_or_default();
        let mut source = Source::new(
            String::new(),
            manifest["name"].as_str().unwrap_or("插件").into(),
            3,
        );
        source.ttl_ms = 0;
        if let Some(defaults) = manifest.get("source_defaults") {
            let _ = apply_settings(&mut source, defaults);
        }
        Self {
            manifest,
            disk: saved.unwrap_or(Disk {
                enabled: false,
                settings: Value::Object(settings),
                state: json!({}),
                source,
                channels: BTreeMap::new(),
            }),
            source: None,
            channels: BTreeMap::new(),
            events: VecDeque::new(),
            running: false,
            epoch: 0,
            next_at: None,
            cancel: Arc::new(Notify::new()),
            status: "已安装，尚未启用".into(),
            error: None,
            last_run: None,
            last_log: String::new(),
        }
    }
}
fn script(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python").join(name)
}
pub(super) async fn python(
    args: Vec<String>,
    input: Vec<u8>,
    limit: usize,
    seconds: u64,
) -> Result<Vec<u8>, String> {
    let mut child = tokio::process::Command::new("python")
        .args(args)
        .env_clear()
        .envs(std::env::vars_os().filter(|(key, _)| {
            matches!(
                key.to_string_lossy().to_ascii_uppercase().as_str(),
                "PATH"
                    | "SYSTEMROOT"
                    | "WINDIR"
                    | "USERPROFILE"
                    | "APPDATA"
                    | "LOCALAPPDATA"
                    | "PROGRAMDATA"
                    | "TEMP"
                    | "TMP"
                    | "SYSTEMDRIVE"
            )
        }))
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("无法启动 Python：{e}"))?;
    let mut stdout = child.stdout.take().unwrap().take(limit as u64 + 1);
    let mut stderr = child.stderr.take().unwrap().take(65537);
    let mut stdin = child.stdin.take().unwrap();
    let result = tokio::time::timeout(Duration::from_secs(seconds), async {
        stdin.write_all(&input).await.map_err(|e| e.to_string())?;
        drop(stdin);
        let mut out = vec![];
        let mut err = vec![];
        let (status, read_out, read_err) = tokio::join!(
            child.wait(),
            stdout.read_to_end(&mut out),
            stderr.read_to_end(&mut err)
        );
        read_out.map_err(|e| e.to_string())?;
        read_err.map_err(|e| e.to_string())?;
        let status = status.map_err(|e| e.to_string())?;
        if out.len() > limit || err.len() > 65536 {
            return Err("插件输出日志或返回内容过大".into());
        }
        if !status.success() {
            return Err(String::from_utf8_lossy(&err)
                .trim()
                .chars()
                .rev()
                .take(2000)
                .collect::<String>()
                .chars()
                .rev()
                .collect());
        }
        Ok(out)
    })
    .await;
    match result {
        Ok(r) => r,
        Err(_) => {
            let _ = child.kill().await;
            Err(format!("插件执行超过 {seconds} 秒，已终止本次执行"))
        }
    }
}
pub async fn initialize(a: Arc<App>) {
    let ids: Vec<_> = a
        .plugins
        .lock()
        .await
        .items
        .iter()
        .filter(|(_, p)| p.disk.enabled)
        .map(|(id, _)| id.clone())
        .collect();
    for id in ids {
        if let Err(e) = set_enabled(a.clone(), &id, true).await {
            log(&mut *a.inner.lock().await, a.now(), e);
        }
    }
    tokio::spawn(supervise(a));
}
pub async fn set_enabled(a: Arc<App>, id: &str, enabled: bool) -> Result<(), String> {
    let mut m = a.plugins.lock().await;
    let p = m.items.get_mut(id).ok_or("插件不存在")?;
    p.epoch += 1;
    p.cancel.notify_one();
    p.events.clear();
    p.next_at = None;
    if let Some(source) = p.source.take() {
        let mut i = a.inner.lock().await;
        if let Some(s) = i.scheduler.source(&source) {
            p.disk.source = s.clone();
        }
        i.audio_pending.retain(|p| p.source != source);
        i.scheduler.remove(&source);
        i.images.remove(&source);
        i.keys.remove(&source);
    }
    {
        let mut i = a.inner.lock().await;
        for (key, source) in std::mem::take(&mut p.channels) {
            if let Some(s) = i.scheduler.source(&source) {
                p.disk.channels.insert(key, s.clone());
            }
            i.audio_pending.retain(|a| a.source != source);
            i.scheduler.remove(&source);
            i.images.remove(&source);
            i.keys.remove(&source);
        }
    }
    p.disk.enabled = enabled;
    p.error = None;
    if enabled {
        p.cancel = Arc::new(Notify::new());
        let id_source = format!("plugin-{id}-{}", uuid::Uuid::new_v4());
        let mut source = p.disk.source.clone();
        source.id = id_source.clone();
        source.revision = 0;
        source.consumed = 0;
        source.order = 0;
        source.updated_at = 0;
        source.boost = None;
        if p.manifest["multi_channel"] != true {
            a.inner.lock().await.scheduler.add(source);
        }
        p.source = Some(id_source);
        p.status = "已启用，等待触发".into();
        if p.manifest["triggers"]["startup"] == true {
            p.events.push_back(json!({"type":"startup"}));
        }
        if let Some(seconds) = p.manifest["triggers"]["interval_seconds"].as_f64() {
            p.next_at = Some(a.now() + (seconds * 1000.) as u64);
        }
    } else {
        p.status = "已禁用".into();
    }
    m.save(id)
}
pub async fn save_source(a: &Arc<App>, source: &str) {
    let mut m = a.plugins.lock().await;
    if let Some(id) = m.owner(source) {
        if let Some(s) = a.inner.lock().await.scheduler.source(source) {
            let redraw = m.items[&id].disk.source.format != s.format;
            if let Some(key) = m.items[&id]
                .channels
                .iter()
                .find(|(_, v)| v.as_str() == source)
                .map(|(k, _)| k.clone())
            {
                m.items
                    .get_mut(&id)
                    .unwrap()
                    .disk
                    .channels
                    .insert(key, s.clone());
                let _ = m.save(&id);
                return;
            }
            m.items.get_mut(&id).unwrap().disk.source = s.clone();
            if redraw {
                let p = m.items.get_mut(&id).unwrap();
                p.epoch += 1;
                p.cancel.notify_one();
                p.cancel = Arc::new(Notify::new());
                p.events.clear();
                p.next_at = None;
                let _ = m.enqueue(&id, json!({"type":"display_settings_changed"}));
            }
            let _ = m.save(&id);
        }
    }
}
pub async fn key(a: &Arc<App>, source: &str, key: &str, action: &str, revision: u64) {
    let mut m = a.plugins.lock().await;
    if let Some(id) = m.owner(source) {
        if m.items[&id].manifest["triggers"]["keys"] == true {
            let event = json!({"type":"key","key":key,"action":action,"revision":revision,"channel":m.items[&id].channels.iter().find(|(_,v)|v.as_str()==source).map(|(k,_)|k.clone())});
            let _ = m.enqueue(&id, event);
        }
    }
}
pub async fn displayed(a: &Arc<App>, frame: &Frame) {
    let mut m = a.plugins.lock().await;
    if let Some(id) = m.owner(&frame.id) {
        if m.items[&id].manifest["triggers"]["displayed"] == true {
            let channel = m.items[&id]
                .channels
                .iter()
                .find(|(_, v)| *v == &frame.id)
                .map(|(k, _)| k.clone());
            let _ = m.enqueue(
                &id,
                json!({"type":"displayed","revision":frame.revision,"channel":channel}),
            );
        }
    }
}
fn static_next_at(manifest: &Value, now: u64) -> Option<u64> {
    manifest["triggers"]["interval_seconds"]
        .as_f64()
        .filter(|n| n.is_finite() && *n >= 1. && *n <= 86400.)
        .map(|n| now + (n * 1000.) as u64)
}

struct Job {
    id: String,
    epoch: u64,
    event: Value,
    request: Value,
    source: String,
    cancel: Arc<Notify>,
    root: PathBuf,
    permit: tokio::sync::OwnedSemaphorePermit,
}
async fn supervise(a: Arc<App>) {
    let mut tick = tokio::time::interval(Duration::from_millis(200));
    loop {
        tick.tick().await;
        let mut jobs = vec![];
        {
            let mut m = a.plugins.lock().await;
            if m.stopping {
                return;
            }
            let now = a.now();
            let root = m.root.clone();
            let slots = m.slots.clone();
            for (id, p) in &mut m.items {
                if !p.disk.enabled {
                    continue;
                }
                if p.next_at.is_some_and(|at| now >= at) {
                    if p.events.len() < 32 && !p.events.iter().any(|e| e["type"] == "interval") {
                        p.events.push_back(json!({"type":"interval"}));
                    }
                    p.next_at = None;
                }
                if p.running || p.events.is_empty() {
                    continue;
                }
                let Ok(permit) = slots.clone().try_acquire_owned() else {
                    continue;
                };
                let event = p.events.pop_front().unwrap();
                p.running = true;
                p.status = "正在生成画面".into();
                let foreground = a.inner.lock().await.scheduler.key_target(now);
                let source = event["channel"]
                    .as_str()
                    .and_then(|k| p.channels.get(k))
                    .cloned()
                    .or_else(|| foreground.filter(|id| p.channels.values().any(|v| v == id)))
                    .or_else(|| p.source.clone())
                    .unwrap();
                let display = {
                    let i = a.inner.lock().await;
                    let rules = i.scheduler.source(&source);
                    json!({"visible":!i.sending&&!i.focus_unknown&&i.scheduler.key_target(now).as_deref()==Some(source.as_str()),"format":rules.map_or("mono",|s|s.format.as_str()),"revision":i.scheduler.current.as_ref().filter(|d|d.frame.id==source).map(|d|d.frame.revision),"now":now,"media_epoch":i.media_epoch,"shown_at":i.scheduler.current.as_ref().filter(|d|d.frame.id==source).map(|d|d.shown_at)})
                };
                let channels = {
                    let i = a.inner.lock().await;
                    p.channels.iter().map(|(key,id)|{
                        let current=i.scheduler.current.as_ref().filter(|d|&d.frame.id==id);
                        (key.clone(),json!({"visible":!i.sending&&!i.focus_unknown&&!i.blocked&&i.scheduler.key_target(now).as_deref()==Some(id.as_str()),"format":i.scheduler.source(id).map_or("mono",|s|s.format.as_str()),"revision":current.map(|d|d.frame.revision),"shown_at":current.map(|d|d.shown_at),"now":now}))
                    }).collect::<serde_json::Map<_,_>>()
                };
                jobs.push(Job{id:id.clone(),epoch:p.epoch,event:event.clone(),request:json!({"entry":p.manifest["entry"],"settings":p.disk.settings,"state":p.disk.state,"display":display,"channels":channels,"event":event}),source,cancel:p.cancel.clone(),root:root.clone(),permit});
            }
        }
        for job in jobs {
            tokio::spawn(execute(a.clone(), job));
        }
    }
}
async fn execute(a: Arc<App>, job: Job) {
    let _permit = job.permit;
    let run = job.root.join("runs").join(uuid::Uuid::new_v4().to_string());
    let mut result = Err("无法创建插件执行目录".into());
    if std::fs::create_dir(&run).is_ok() {
        let output = run.join("frame.png");
        let args = vec![
            script("plugin_worker.py").to_string_lossy().into(),
            job.root
                .join("packages")
                .join(&job.id)
                .to_string_lossy()
                .into(),
            output.to_string_lossy().into(),
            job.root
                .join("data")
                .join(&job.id)
                .join("files")
                .to_string_lossy()
                .into(),
        ];
        let request = serde_json::to_vec(&job.request).unwrap();
        result = tokio::select! {_=job.cancel.notified()=>Err("已取消".into()),r=python(args,request,96*1024,15)=>match r{Ok(raw)=>match serde_json::from_slice::<Value>(&raw){Ok(value)=>{if value["shown"]==true{match tokio::fs::read(&output).await{Ok(bytes) if bytes.len()<=8*1024*1024=>{let normalized=tokio::task::spawn_blocking(move||validate_frame(&bytes)).await;match normalized{Ok(Ok(png))=>Ok((value,Some(png))),_=>Err("插件输出不是有效 PNG".into())}},_=>Err("插件没有生成有效图片".into())}}else{Ok((value,None))}},Err(e)=>Err(format!("插件返回格式错误：{e}"))},Err(e)=>Err(e)}};
    }
    let result = result.and_then(|(value, png)| {
        let audio = if value["audio"].is_null() {
            None
        } else {
            if value["audio"]["path"] != "frame.wav" {
                return Err("音频输出路径不正确".into());
            }
            let volume = value["audio"]["volume"]
                .as_u64()
                .filter(|v| *v <= 100)
                .ok_or("音量不正确")? as u8;
            let path = run.join("frame.wav");
            let meta = std::fs::symlink_metadata(&path).map_err(|e| e.to_string())?;
            if !meta.file_type().is_file() || meta.len() > 98304 {
                return Err("声音文件不正确或超过 96 KiB".into());
            }
            let raw = std::fs::read(path).map_err(|e| e.to_string())?;
            Some((super::audio::decode(&raw)?, volume))
        };
        let mut channels = Vec::new();
        if let Some(items) = value["channels"].as_array() {
            if items.len() > 32 {
                return Err("插件最多注册 32 个通道".into());
            }
            let mut keys = std::collections::HashSet::new();
            for ch in items {
                let key = ch["key"].as_str().ok_or("缺少通道 ID")?;
                if !slug(key) || !keys.insert(key) {
                    return Err("通道 ID 无效或重复".into());
                }
                let name = ch["name"]
                    .as_str()
                    .filter(|n| !n.trim().is_empty() && n.len() <= 120)
                    .ok_or("通道名称无效")?;
                let mut rules = Source::new(String::new(), name.into(), 3);
                apply_settings(&mut rules, &ch["rules"])?;
                if !["mono", "gray4", "gray16"].contains(&ch["format"].as_str().unwrap_or("mono")) {
                    return Err("通道灰阶无效".into());
                }
                let png = if ch["shown"] == true {
                    Some(validate_frame(
                        &std::fs::read(run.join(format!("channel-{key}.png")))
                            .map_err(|e| e.to_string())?,
                    )?)
                } else {
                    None
                };
                channels.push((ch.clone(), png));
            }
        }
        Ok((value, png, audio, channels))
    });
    {
        let mut m = a.plugins.lock().await;
        if let Some(p) = m.items.get_mut(&job.id) {
            p.running = false;
            if p.disk.enabled && p.epoch == job.epoch {
                p.last_run = Some(a.now());
                match result {
                    Ok((value, png, audio, channels)) => {
                        let mut i = a.inner.lock().await;
                        let still_visible = !i.blocked
                            && !i.recording
                            && !i.sending
                            && !i.focus_unknown
                            && i.scheduler.key_target(a.now()).as_deref()
                                == Some(job.source.as_str())
                            && i.scheduler.current.as_ref().is_some_and(|d| {
                                Some(d.frame.revision)
                                    == job.request["display"]["revision"].as_u64()
                            });
                        let stale_key = job.event["type"] == "key"
                            && (!still_visible
                                || job.event["revision"].as_u64()
                                    != job.request["display"]["revision"].as_u64());
                        if (value["require_visible"] == true && !still_visible) || stale_key {
                            p.status = "已暂停，等待重新显示".into();
                            // Keep declared background polling alive after a discarded foreground render.
                            // A displayed-only plugin has no static interval and stays paused.
                            p.next_at = static_next_at(&p.manifest, a.now());
                            p.error = None;
                        } else {
                            if p.manifest["multi_channel"] == true {
                                let desired: std::collections::HashSet<_> = channels
                                    .iter()
                                    .filter_map(|(c, _)| c["key"].as_str())
                                    .collect();
                                let removed: Vec<_> = p
                                    .channels
                                    .iter()
                                    .filter(|(k, _)| !desired.contains(k.as_str()))
                                    .map(|(k, v)| (k.clone(), v.clone()))
                                    .collect();
                                for (key, id) in removed {
                                    p.channels.remove(&key);
                                    p.disk.channels.remove(&key);
                                    i.scheduler.remove(&id);
                                    i.images.remove(&id);
                                    i.keys.remove(&id);
                                    i.audio_pending.retain(|a| a.source != id);
                                }
                                for (ch, png) in channels {
                                    let key = ch["key"].as_str().unwrap().to_string();
                                    let id = p
                                        .channels
                                        .entry(key.clone())
                                        .or_insert_with(|| {
                                            format!("plugin-{}-{}", job.id, uuid::Uuid::new_v4())
                                        })
                                        .clone();
                                    if i.scheduler.source(&id).is_none() {
                                        let mut s = p
                                            .disk
                                            .channels
                                            .get(&key)
                                            .cloned()
                                            .unwrap_or_else(|| p.disk.source.clone());
                                        s.id = id.clone();
                                        s.name = ch["name"].as_str().unwrap().into();
                                        if !p.disk.channels.contains_key(&key)
                                            || job.event["type"] == "settings_changed"
                                        {
                                            apply_settings(&mut s, &ch["rules"]).unwrap();
                                        }
                                        s.revision = 0;
                                        s.consumed = 0;
                                        s.order = 0;
                                        s.updated_at = 0;
                                        s.boost = None;
                                        i.scheduler.add(s);
                                    } else {
                                        let s = i.scheduler.source_mut(&id).unwrap();
                                        s.name = ch["name"].as_str().unwrap().into();
                                        if job.event["type"] == "settings_changed" {
                                            apply_settings(s, &ch["rules"]).unwrap();
                                        }
                                    }
                                    let current =
                                        i.scheduler.current.as_ref().filter(|d| d.frame.id == id);
                                    let visible = !i.sending
                                        && !i.focus_unknown
                                        && !i.blocked
                                        && i.scheduler.key_target(a.now()).as_deref()
                                            == Some(id.as_str());
                                    let same = current.map(|d| d.frame.revision)
                                        == job.request["channels"][&key]["revision"].as_u64();
                                    if ch["require_visible"] == true && (!visible || !same) {
                                        continue;
                                    }
                                    if let Some(png) = png {
                                        i.images.insert(id.clone(), png);
                                        let _ = i.scheduler.update(&id, a.now());
                                        let s = i.scheduler.source_mut(&id).unwrap();
                                        if !s.format_override {
                                            s.format = ch["format"].as_str().unwrap_or("mono").into();
                                        }
                                    }
                                }
                            }
                            p.disk.state = value["state"].clone();
                            p.last_log = value["log"].as_str().unwrap_or_default().into();
                            p.error = None;
                            p.status = "等待下次触发".into();
                            let seconds = value["after_seconds"]
                                .as_f64()
                                .or_else(|| p.manifest["triggers"]["interval_seconds"].as_f64());
                            p.next_at = seconds
                                .filter(|n| n.is_finite() && *n >= 1. && *n <= 86400.)
                                .map(|n| a.now() + (n * 1000.) as u64);
                            let mut audio_revision = None;
                            if let Some(png) = png {
                                let relevant = job.event["type"] != "key"
                                    || i.scheduler.current.as_ref().is_some_and(|d| {
                                        d.frame.id == job.source
                                            && Some(d.frame.revision)
                                                == job.event["revision"].as_u64()
                                    });
                                if relevant && i.scheduler.source(&job.source).is_some() {
                                    i.images.insert(job.source.clone(), png);
                                    let _ = i.scheduler.update(&job.source, a.now());
                                    audio_revision =
                                        i.scheduler.source(&job.source).map(|s| s.revision);
                                    if let Some(s) = i.scheduler.source_mut(&job.source).filter(|s| !s.format_override) {
                                        s.format =
                                            value["format"].as_str().unwrap_or("mono").into();
                                    }
                                }
                            } else if still_visible && job.request["display"]["visible"] == true {
                                audio_revision = job.request["display"]["revision"].as_u64();
                            }
                            if let (Some((clip, volume)), Some(revision)) = (audio, audio_revision)
                            {
                                if !i.blocked
                                    && !i.recording
                                    && !i.scheduler.paused
                                    && job.request["display"]["media_epoch"].as_u64()
                                        == Some(i.media_epoch)
                                {
                                    i.audio_pending.retain(|p| p.source != job.source);
                                    i.audio_pending.push(super::audio::Pending {
                                        source: job.source.clone(),
                                        revision,
                                        clip,
                                        volume,
                                    });
                                }
                            }
                        }
                    }
                    Err(e) => {
                        p.error = Some(e);
                        p.status = "本次执行失败".into();
                        p.next_at = p.manifest["triggers"]["interval_seconds"]
                            .as_f64()
                            .map(|n| a.now() + (n * 1000.) as u64);
                    }
                }
                let _ = m.save(&job.id);
            }
        }
    }
    // Remove only this host-generated UUID directory inside the verified plugin runs root.
    if let (Ok(target), Ok(parent)) = (run.canonicalize(), job.root.join("runs").canonicalize()) {
        if target.parent() == Some(parent.as_path()) {
            let _ = std::fs::remove_dir_all(target);
        }
    }
}
pub async fn shutdown(a: &Arc<App>) {
    {
        let mut m = a.plugins.lock().await;
        m.stopping = true;
        for p in m.items.values_mut() {
            p.cancel.notify_one();
            p.epoch += 1;
            p.events.clear();
            p.next_at = None;
        }
    }
    for _ in 0..50 {
        if !a.plugins.lock().await.items.values().any(|p| p.running) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

pub async fn install(State(a): State<Arc<App>>, h: HeaderMap, bytes: Bytes) -> ApiResult {
    auth(&a, &h)?;
    let _operation = a.plugin_operation.lock().await;
    let root = a.plugins.lock().await.root.clone();
    let raw = python(
        vec![
            script("plugin_tools.py").to_string_lossy().into(),
            "install".into(),
            root.to_string_lossy().into(),
        ],
        bytes.to_vec(),
        65536,
        10,
    )
    .await
    .map_err(bad)?;
    let manifest: Value = serde_json::from_slice(&raw).map_err(bad)?;
    let id = manifest["id"]
        .as_str()
        .ok_or_else(|| bad("插件缺少 ID"))?
        .to_string();
    let mut m = a.plugins.lock().await;
    m.items.insert(id.clone(), Plugin::new(manifest, None));
    m.save(&id).map_err(bad)?;
    Ok(Json(json!({"id":id,"enabled":false})))
}
#[derive(Deserialize)]
pub struct Control {
    op: String,
    #[serde(default)]
    data: Value,
}
pub async fn control(
    State(a): State<Arc<App>>,
    Path(id): Path<String>,
    h: HeaderMap,
    Json(c): Json<Control>,
) -> ApiResult {
    auth(&a, &h)?;
    if !slug(&id) {
        return Err(bad("插件 ID 无效"));
    }
    let _operation = a.plugin_operation.lock().await;
    match c.op.as_str() {
        "enable" => set_enabled(a.clone(), &id, true).await.map_err(bad)?,
        "disable" => set_enabled(a.clone(), &id, false).await.map_err(bad)?,
        "run" => {
            let mut m = a.plugins.lock().await;
            let action = text(&c.data, "action", "refresh");
            let p = m.items.get(&id).ok_or_else(|| bad("插件不存在"))?;
            if action != "refresh"
                && !p.manifest["triggers"]["actions"]
                    .as_array()
                    .is_some_and(|actions| actions.iter().any(|v| v["id"] == action))
            {
                return Err(bad("插件未注册此操作"));
            }
            let channel = c.data["channel"].as_str();
            if channel.is_some_and(|key| !p.channels.contains_key(key)) {
                return Err(bad("插件通道不存在"));
            }
            m.enqueue(
                &id,
                json!({"type":"manual","action":action,"channel":channel}),
            )
            .map_err(bad)?;
        }
        "settings" => {
            let fields = a
                .plugins
                .lock()
                .await
                .items
                .get(&id)
                .ok_or_else(|| bad("插件不存在"))?
                .manifest["settings"]
                .clone();
            let raw=python(vec![script("plugin_tools.py").to_string_lossy().into(),"validate-settings".into()],serde_json::to_vec(&json!({"fields":fields.as_array().cloned().unwrap_or_default(),"values":c.data})).unwrap(),65536,5).await.map_err(bad)?;
            let settings: Value = serde_json::from_slice(&raw).map_err(bad)?;
            let mut m = a.plugins.lock().await;
            let p = m.items.get_mut(&id).unwrap();
            p.disk.settings = settings;
            p.epoch += 1;
            p.cancel.notify_one();
            p.cancel = Arc::new(Notify::new());
            p.events.clear();
            p.next_at = None;
            if p.disk.enabled {
                p.events.push_back(json!({"type":"settings_changed"}));
            }
            m.save(&id).map_err(bad)?;
        }
        "uninstall" => {
            set_enabled(a.clone(), &id, false).await.map_err(bad)?;
            for _ in 0..50 {
                if !a.plugins.lock().await.items[&id].running {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            let mut m = a.plugins.lock().await;
            if m.items[&id].running {
                return Err(bad("插件仍在退出，请稍后重试"));
            }
            for sub in ["packages", "data"] {
                let parent = m.root.join(sub).canonicalize().map_err(bad)?;
                let target = parent.join(&id);
                if target.exists() {
                    let resolved = target.canonicalize().map_err(bad)?;
                    if resolved.parent() != Some(parent.as_path()) {
                        return Err(bad("插件目录越界，未执行删除"));
                    }
                    std::fs::remove_dir_all(resolved).map_err(bad)?;
                }
            }
            m.items.remove(&id);
        }
        _ => return Err(bad("未知插件操作")),
    }
    Ok(Json(json!({"ok":true})))
}
pub async fn page(State(a): State<Arc<App>>, Path(id): Path<String>) -> Response {
    if !slug(&id) {
        return StatusCode::NOT_FOUND.into_response();
    }
    let m = a.plugins.lock().await;
    let Some(p) = m.items.get(&id) else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Some(page) = p.manifest["homepage"]
        .as_str()
        .or_else(|| p.manifest["settings_page"].as_str())
    else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let root = m.root.join("packages").join(id);
    let Ok(path) = root.join(page).canonicalize() else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Ok(root) = root.canonicalize() else {
        return StatusCode::NOT_FOUND.into_response();
    };
    if !path.starts_with(root) || std::fs::metadata(&path).map_or(true, |m| m.len() > 256 * 1024) {
        return StatusCode::NOT_FOUND.into_response();
    }
    match std::fs::read(path) {
        Ok(bytes) => ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], bytes).into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

pub async fn export(State(a): State<Arc<App>>, Path(id): Path<String>, h: HeaderMap) -> Response {
    if let Err(error) = auth(&a, &h) {
        return error.into_response();
    }
    if !slug(&id) {
        return bad("插件 ID 无效").into_response();
    }
    let _operation = a.plugin_operation.lock().await;
    let m = a.plugins.lock().await;
    if !m.items.contains_key(&id) {
        return StatusCode::NOT_FOUND.into_response();
    }
    let root = m.root.clone();
    drop(m);
    match python(
        vec![
            script("plugin_tools.py").to_string_lossy().into(),
            "export".into(),
            root.to_string_lossy().into(),
            id.clone(),
        ],
        vec![],
        10 * 1024 * 1024,
        10,
    )
    .await
    {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, "application/zip".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"{id}.screen-plugin.zip\""),
                ),
            ],
            bytes,
        )
            .into_response(),
        Err(e) => bad(e).into_response(),
    }
}

fn validate_frame(bytes: &[u8]) -> Result<Vec<u8>, String> {
    if bytes.len() > 8 * 1024 * 1024 {
        return Err("插件图片超过 8 MiB".into());
    }
    let mut reader =
        image::ImageReader::with_format(std::io::Cursor::new(bytes), image::ImageFormat::Png);
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(400);
    limits.max_image_height = Some(300);
    limits.max_alloc = Some(8 * 1024 * 1024);
    reader.limits(limits);
    let image = reader.decode().map_err(|e| e.to_string())?;
    if image.width() != 400 || image.height() != 300 {
        return Err("插件必须提交 400×300 PNG；铺满方式请在插件内处理".into());
    }
    Ok(bytes.to_vec())
}
