//! SDK-style HTTP producer client. show succeeds on scheduler acceptance, not screen refresh.
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc,
};
use tokio::sync::{watch, Mutex};
pub use zectrix_core::{
    DeviceSummary, DisconnectReason, Error, Event, ImageFormat, Key, KeyAction, OpenOptions, Result,
};

#[derive(Clone, Debug, Deserialize)]
pub struct Receipt {
    pub sequence: u64,
    pub revision: u64,
    pub state: String,
    pub error: Option<String>,
}
struct Session {
    http: reqwest::Client,
    url: String,
    token: String,
    closed: AtomicBool,
    sequence: AtomicU64,
    stop: watch::Sender<bool>,
}
pub struct Device {
    pub summary: DeviceSummary,
    session: Arc<Session>,
    events: Mutex<(u64, bool)>,
}
fn transport(e: impl ToString) -> Error {
    Error::TransportFailure(e.to_string())
}
async fn response(r: reqwest::Response) -> Result<Value> {
    let status = r.status();
    if status.is_success() {
        r.json().await.map_err(transport)
    } else {
        let message = r.text().await.unwrap_or_default();
        match status.as_u16() {
            401 | 404 => Err(Error::Disconnected),
            429 => Err(Error::Busy),
            400 | 409 => Err(Error::InvalidOptions(message)),
            _ => Err(transport(message)),
        }
    }
}
impl Drop for Device {
    fn drop(&mut self) {
        let _ = self.session.stop.send(true);
    }
}
impl Device {
    pub async fn open(options: OpenOptions) -> Result<Self> {
        let key = std::env::var("SCREEN_SCHEDULER_KEY").map_err(|_| {
            Error::InvalidOptions("请设置 SCREEN_SCHEDULER_KEY，或调用 open_with_key".into())
        })?;
        Self::open_with_key(options, &key).await
    }
    pub async fn open_with_key(options: OpenOptions, key: &str) -> Result<Self> {
        let mut base = options.target.unwrap_or("http://127.0.0.1:38477".into());
        if !base.starts_with("http://") {
            base = format!("http://{base}");
        }
        let url = reqwest::Url::parse(&base).map_err(transport)?;
        if url.scheme() != "http"
            || url.host_str().is_none()
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err(Error::InvalidOptions("目标应为调度台 HTTP 地址".into()));
        }
        if url.port().is_none() {
            base = format!("http://{}:38477", url.host_str().unwrap());
        }
        base = base.trim_end_matches('/').into();
        let http = reqwest::Client::builder()
            .no_proxy()
            .timeout(std::time::Duration::from_secs(8))
            .build()
            .map_err(transport)?;
        let value = response(
            http.post(format!("{base}/v1/sessions"))
                .bearer_auth(key)
                .json(&json!({"name":options.client_name.unwrap_or("HTTP 图片来源".into())}))
                .send()
                .await
                .map_err(transport)?,
        )
        .await?;
        let id = value["id"]
            .as_str()
            .ok_or_else(|| transport("invalid session response"))?
            .to_string();
        let token = value["token"]
            .as_str()
            .ok_or_else(|| transport("invalid session token"))?
            .to_string();
        let (stop, mut receive) = watch::channel(false);
        let session = Arc::new(Session {
            http,
            url: format!("{base}/v1/sessions/{id}"),
            token,
            closed: AtomicBool::new(false),
            sequence: AtomicU64::new(0),
            stop,
        });
        let heart = session.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {_=receive.changed()=>break,_=tokio::time::sleep(std::time::Duration::from_secs(5))=>{let result=heart.http.post(format!("{}/heartbeat",heart.url)).bearer_auth(&heart.token).send().await;if !result.is_ok_and(|r|r.status().is_success()){heart.closed.store(true,Ordering::SeqCst);break;}}}
            }
            let _ = heart
                .http
                .delete(&heart.url)
                .bearer_auth(&heart.token)
                .send()
                .await;
        });
        Ok(Self {
            summary: DeviceSummary {
                id,
                name: "Screen Scheduler (managed)".into(),
                address: base,
                busy: false,
            },
            session,
            events: Mutex::new((0, false)),
        })
    }
    pub fn last_sequence(&self) -> u64 {
        self.session.sequence.load(Ordering::SeqCst)
    }
    pub async fn show(&self, png: &[u8]) -> Result<()> {
        self.show_with_format(png, ImageFormat::Mono).await
    }
    pub async fn show_with_format(&self, png: &[u8], format: ImageFormat) -> Result<()> {
        self.submit(png, format).await.map(|_| ())
    }
    pub async fn submit(&self, png: &[u8], format: ImageFormat) -> Result<Receipt> {
        let sequence = self.session.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        self.submit_with_sequence(png, format, sequence).await
    }
    pub async fn submit_with_sequence(
        &self,
        png: &[u8],
        format: ImageFormat,
        sequence: u64,
    ) -> Result<Receipt> {
        if self.session.closed.load(Ordering::SeqCst) {
            return Err(Error::Disconnected);
        }
        if png.len() > 8 * 1024 * 1024 {
            return Err(Error::InvalidImage("PNG 超过 8 MiB".into()));
        }
        self.session.sequence.fetch_max(sequence, Ordering::SeqCst);
        let value = response(
            self.session
                .http
                .post(format!("{}/frames/{sequence}", self.session.url))
                .bearer_auth(&self.session.token)
                .header("content-type", "image/png")
                .header(
                    "x-image-format",
                    match format {
                        ImageFormat::Mono => "mono",
                        ImageFormat::Gray4 => "gray4",
                        ImageFormat::Gray16 => "gray16",
                    },
                )
                .body(png.to_vec())
                .send()
                .await
                .map_err(transport)?,
        )
        .await?;
        serde_json::from_value(value).map_err(transport)
    }
    pub async fn receipt(&self, sequence: u64) -> Result<Receipt> {
        let result = self
            .session
            .http
            .get(format!("{}/frames/{sequence}", self.session.url))
            .bearer_auth(&self.session.token)
            .send()
            .await
            .map_err(transport)?;
        if result.status().as_u16() == 404 {
            return Err(Error::ResultUnknown);
        }
        let value = response(result).await?;
        serde_json::from_value(value).map_err(transport)
    }
    /// Attach one short PCM16 WAV to a frame. Success means managed acceptance.
    /// Retry uncertain requests with exactly the same sequence, WAV and volume.
    pub async fn play_wav(&self, sequence: u64, wav: &[u8], volume: u8) -> Result<()> {
        if self.session.closed.load(Ordering::SeqCst) {
            return Err(Error::Disconnected);
        }
        if sequence == 0 || volume > 100 || wav.len() > 98304 {
            return Err(Error::InvalidOptions(
                "请指定已提交画面、0～100 音量和不超过 96 KiB 的 WAV".into(),
            ));
        }
        response(
            self.session
                .http
                .post(format!("{}/frames/{sequence}/audio", self.session.url))
                .bearer_auth(&self.session.token)
                .header("content-type", "audio/wav")
                .header("x-audio-volume", volume.to_string())
                .body(wav.to_vec())
                .send()
                .await
                .map_err(transport)?,
        )
        .await?;
        Ok(())
    }
    pub async fn next_event(&self) -> Result<Option<Event>> {
        let mut cursor = self.events.lock().await;
        loop {
            if self.session.closed.load(Ordering::SeqCst) {
                if cursor.1 {
                    return Ok(None);
                }
                cursor.1 = true;
                return Ok(Some(Event::Disconnected {
                    reason: DisconnectReason::Network,
                }));
            }
            let value = response(
                self.session
                    .http
                    .get(format!("{}/events?after={}", self.session.url, cursor.0))
                    .bearer_auth(&self.session.token)
                    .send()
                    .await
                    .map_err(transport)?,
            )
            .await?;
            if value["gap"] == true {
                cursor.0 = value["cursor"].as_u64().unwrap_or(cursor.0);
                return Err(Error::ConsumerTooSlow);
            }
            if let Some(e) = value["events"].as_array().and_then(|events| events.first()) {
                cursor.0 = e["cursor"].as_u64().unwrap_or(cursor.0);
                let key = match e["key"].as_str() {
                    Some("Up") => Key::Up,
                    Some("Down") => Key::Down,
                    _ => Key::Confirm,
                };
                let action = if e["action"] == "Long" {
                    KeyAction::Long
                } else {
                    KeyAction::Short
                };
                return Ok(Some(Event::Key { key, action }));
            }
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
    }
    pub async fn close(&self) -> Result<()> {
        if self.session.closed.swap(true, Ordering::SeqCst) {
            return Ok(());
        }
        let _ = self.session.stop.send(true);
        let r = self
            .session
            .http
            .delete(&self.session.url)
            .bearer_auth(&self.session.token)
            .send()
            .await
            .map_err(transport)?;
        if r.status().as_u16() == 401 {
            return Ok(());
        }
        response(r).await.map(|_| ())
    }
}
