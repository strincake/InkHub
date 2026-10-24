//! Producer protocols. Managed acceptance is deliberately distinct from device display.
use super::*;
use axum::extract::Query;
use axum::routing::delete;
use note4_screen_scheduler::lan::{uniform_palette, IncomingAudio, IncomingImage, Packet};
use std::{
    collections::VecDeque,
    hash::{Hash, Hasher},
    io::Cursor,
    net::SocketAddr,
};

#[derive(Clone, Serialize)]
pub struct Receipt {
    pub sequence: u64,
    pub revision: u64,
    pub state: String,
    pub error: Option<String>,
    #[serde(skip)]
    fingerprint: u64,
    #[serde(skip)]
    audio_fingerprint: Option<u64>,
}
pub struct Session {
    pub name: String,
    pub token: String,
    pub transport: String,
    pub seen: u64,
    pub sequence: u64,
    pub receipts: VecDeque<Receipt>,
    pub events: VecDeque<Value>,
    pub event_serial: u64,
}
impl Session {
    fn new(name: &str, transport: &str, now: u64) -> Self {
        Self {
            name: name.into(),
            token: uuid::Uuid::new_v4().to_string(),
            transport: transport.into(),
            seen: now,
            sequence: 0,
            receipts: VecDeque::new(),
            events: VecDeque::new(),
            event_serial: 0,
        }
    }
    pub fn push_key(&mut self, key: &str, action: &str, revision: u64, now: u64) {
        self.event_serial += 1;
        self.events.push_back(json!({"cursor":self.event_serial,"type":"key","key":key,"action":action,"revision":revision,"at":now}));
        while self.events.len() > 64 {
            self.events.pop_front();
        }
    }
}
pub fn summaries(i: &Inner) -> Value {
    json!(i
        .external
        .iter()
        .map(|(id, s)| json!({"id":id,"name":s.name,"transport":s.transport,"receipts":s.receipts}))
        .collect::<Vec<_>>())
}
pub fn queue(i: &Inner, now: u64) -> Value {
    let mut snapshot = i.scheduler.clone();
    let next = snapshot.next(now);
    let mut rows: Vec<_> = i
        .scheduler
        .sources
        .iter()
        .filter(|s| s.enabled && (s.valid(now) || s.revision == 0))
        .filter(|s| {
            s.revision > s.consumed
                || s.persistent
                || s.revision == 0
                || i.scheduler
                    .current
                    .as_ref()
                    .is_some_and(|d| d.frame.id == s.id)
        })
        .collect();
    rows.sort_by_key(|s| {
        (
            if i.in_flight.as_ref().is_some_and(|f| f.id == s.id) {
                0
            } else if i
                .scheduler
                .current
                .as_ref()
                .is_some_and(|d| d.frame.id == s.id)
            {
                1
            } else if next.as_ref().is_some_and(|f| f.id == s.id) {
                2
            } else {
                3
            },
            s.effective(now),
            std::cmp::Reverse(s.order),
        )
    });
    let rows:Vec<_>=rows.iter().map(|s| {
        let shown=i.scheduler.current.as_ref().filter(|d|d.frame.id==s.id).map(|d|d.frame.revision);
        let sending=i.in_flight.as_ref().filter(|f|f.id==s.id).map(|f|f.revision);
        let role=if sending.is_some(){"sending"}else if shown.is_some_and(|r|r!=s.revision){"updating"}else if shown.is_some(){"current"}else if next.as_ref().is_some_and(|f|f.id==s.id){"next"}else if s.revision==0{"empty"}else if s.revision<=s.consumed{"fallback"}else{"waiting"};
        json!({"id":s.id,"name":s.name,"priority":s.effective(now),"revision":s.revision,"shown_revision":shown,"sending_revision":sending,"role":role,"reason":i.scheduler.reason(&s.id,now),"ttl_remaining_ms":if s.ttl_ms==0{None}else{Some(s.ttl_ms.saturating_sub(now.saturating_sub(s.updated_at)))},"transport":i.external.get(&s.id).map(|s|s.transport.as_str()).unwrap_or(if s.id.starts_with("plugin-"){"plugin"}else{"test"})})
    }).collect();
    json!({"paused":i.scheduler.paused,"sending":i.sending,"blocked":i.blocked,"next":next,"rows":rows})
}
pub fn mark(i: &mut Inner, frame: &Frame, status: &str, error: Option<String>) {
    if let Some(s) = i.external.get_mut(&frame.id) {
        if let Some(r) = s.receipts.iter_mut().find(|r| r.revision == frame.revision) {
            r.state = status.into();
            r.error = error;
        }
    }
}
pub async fn expire(a: &Arc<App>) {
    let mut i = a.inner.lock().await;
    let now = a.now();
    let dead: Vec<_> = i
        .external
        .iter()
        .filter(|(_, s)| now.saturating_sub(s.seen) >= 15000)
        .map(|(id, _)| id.clone())
        .collect();
    for id in dead {
        remove(&mut i, &id);
        log(&mut i, now, "外部来源心跳已超时，任务已移除");
    }
    let expired: Vec<_> = i
        .external
        .keys()
        .filter_map(|id| {
            i.scheduler
                .source(id)
                .filter(|s| s.revision > 0 && !s.valid(now))
                .map(|s| Frame {
                    id: id.clone(),
                    revision: s.revision,
                })
        })
        .collect();
    for f in expired {
        if let Some(s) = i.external.get_mut(&f.id) {
            if let Some(r) = s
                .receipts
                .iter_mut()
                .find(|r| r.revision == f.revision && r.state == "accepted")
            {
                r.state = "expired".into();
            }
        }
    }
}
fn remove(i: &mut Inner, id: &str) {
    i.audio_pending.retain(|p| p.source != id);
    i.scheduler.remove(id);
    i.images.remove(id);
    i.keys.remove(id);
    i.external.remove(id);
}
fn bearer(h: &HeaderMap) -> &str {
    h.get(header::AUTHORIZATION)
        .and_then(|s| s.to_str().ok())
        .and_then(|s| s.strip_prefix("Bearer "))
        .unwrap_or("")
}
fn authorize(i: &Inner, id: &str, h: &HeaderMap, now: u64) -> Result<(), (StatusCode, String)> {
    match i.external.get(id) {
        Some(s)
            if s.transport == "http"
                && s.token == bearer(h)
                && now.saturating_sub(s.seen) < 15000 =>
        {
            Ok(())
        }
        _ => Err((StatusCode::UNAUTHORIZED, "来源会话无效或已退出".into())),
    }
}
fn register(
    i: &mut Inner,
    name: &str,
    transport: &str,
    now: u64,
) -> Result<String, (StatusCode, String)> {
    if i.external.len() >= 64 {
        return Err((StatusCode::TOO_MANY_REQUESTS, "最多 64 个外部来源".into()));
    }
    let name = name.trim();
    if name.is_empty() || name.len() > 120 || name.chars().any(char::is_control) {
        return Err(bad("来源名称无效"));
    }
    let id = uuid::Uuid::new_v4().to_string();
    i.scheduler.add(Source::new(id.clone(), name.into(), 3));
    i.external.insert(id.clone(), Session::new(name, transport, now));
    Ok(id)
}
fn publish(
    i: &mut Inner,
    id: &str,
    sequence: u64,
    fingerprint: u64,
    png: Vec<u8>,
    format: &str,
    now: u64,
) -> Result<Receipt, (StatusCode, String)> {
    let session = i.external.get(id).ok_or_else(|| bad("来源已退出"))?;
    if let Some(r) = session.receipts.iter().find(|r| r.sequence == sequence) {
        if r.fingerprint == fingerprint {
            return Ok(r.clone());
        }
        return Err((StatusCode::CONFLICT, "同一序号不能提交不同内容".into()));
    }
    if sequence == 0 || sequence <= session.sequence {
        return Err((
            StatusCode::CONFLICT,
            "画面序号必须递增；旧回执已不在保留窗口".into(),
        ));
    }
    i.scheduler.update(id, now).map_err(bad)?;
    let source = i.scheduler.source_mut(id).unwrap();
    if !source.format_override {
        source.format = format.into();
    }
    let revision = source.revision;
    i.images.insert(id.into(), png);
    let session = i.external.get_mut(id).unwrap();
    for r in &mut session.receipts {
        if r.state == "accepted" {
            r.state = "superseded".into();
        }
    }
    let receipt = Receipt {
        sequence,
        revision,
        state: "accepted".into(),
        error: None,
        fingerprint,
        audio_fingerprint: None,
    };
    session.sequence = sequence;
    session.receipts.push_back(receipt.clone());
    while session.receipts.len() > 32 {
        session.receipts.pop_front();
    }
    Ok(receipt)
}
// At most one short cue per image revision. A retry never replays a consumed cue.
fn queue_audio(
    i: &mut Inner,
    id: &str,
    revision: u64,
    clip: zectrix_sdk::AudioClip,
    volume: u8,
    now: u64,
) -> Result<(), (StatusCode, String)> {
    if i.blocked
        || i.focus_unknown
        || i.recording
        || i.scheduler.paused
        || (i.mode == "device" && i.device.is_none())
        || !i
            .scheduler
            .source(id)
            .is_some_and(|s| s.valid(now) && s.revision == revision)
    {
        return Err((StatusCode::CONFLICT, "来源画面无效或媒体已暂停".into()));
    }
    i.audio_pending.retain(|p| p.source != id);
    i.audio_pending.push(audio::Pending {
        source: id.into(),
        revision,
        clip,
        volume,
    });
    Ok(())
}
fn fingerprint(bytes: &[u8], format: &str) -> u64 {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    bytes.hash(&mut h);
    format.hash(&mut h);
    h.finish()
}
pub(super) fn normalize(bytes: &[u8], fit: &str) -> Result<Vec<u8>, String> {
    let mut reader = image::ImageReader::with_format(Cursor::new(bytes), image::ImageFormat::Png);
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(4096);
    limits.max_image_height = Some(4096);
    limits.max_alloc = Some(96 * 1024 * 1024);
    reader.limits(limits);
    let img = reader.decode().map_err(|e| e.to_string())?;
    let img = if fit == "cover" {
        img.resize_to_fill(400, 300, image::imageops::FilterType::Lanczos3)
    } else {
        img.resize(400, 300, image::imageops::FilterType::Lanczos3)
    }
    .to_rgba8();
    let mut base = image::RgbaImage::from_pixel(400, 300, image::Rgba([255, 255, 255, 255]));
    image::imageops::overlay(
        &mut base,
        &img,
        ((400 - img.width()) / 2) as i64,
        ((300 - img.height()) / 2) as i64,
    );
    let mut output = Cursor::new(vec![]);
    image::DynamicImage::ImageRgba8(base)
        .write_to(&mut output, image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(output.into_inner())
}

#[derive(Deserialize)]
struct Registration {
    name: String,
}
async fn open(
    State(a): State<Arc<App>>,
    h: HeaderMap,
    Json(body): Json<Registration>,
) -> ApiResult {
    if bearer(&h) != a.api_key {
        return Err((StatusCode::UNAUTHORIZED, "接入密钥不正确".into()));
    }
    let mut i = a.inner.lock().await;
    let id = register(&mut i, &body.name, "http", a.now())?;
    Ok(Json(
        json!({"id":id,"token":i.external[&id].token,"lease_ms":15000,"heartbeat_ms":5000,"semantics":"accepted_by_scheduler"}),
    ))
}
async fn heartbeat(State(a): State<Arc<App>>, Path(id): Path<String>, h: HeaderMap) -> ApiResult {
    let mut i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    i.external.get_mut(&id).unwrap().seen = a.now();
    Ok(Json(json!({"ok":true,"lease_ms":15000})))
}
async fn close(State(a): State<Arc<App>>, Path(id): Path<String>, h: HeaderMap) -> ApiResult {
    let mut i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    remove(&mut i, &id);
    Ok(Json(json!({"ok":true})))
}
async fn frame(
    State(a): State<Arc<App>>,
    Path((id, sequence)): Path<(String, u64)>,
    h: HeaderMap,
    bytes: Bytes,
) -> ApiResult {
    let format = h
        .get("x-image-format")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("mono")
        .to_string();
    if !["mono", "gray4", "gray16"].contains(&format.as_str()) {
        return Err(bad("支持 mono / gray4 / gray16"));
    }
    let hash = fingerprint(&bytes, &format);
    let fit = {
        let i = a.inner.lock().await;
        authorize(&i, &id, &h, a.now())?;
        if let Some(r) = i.external[&id]
            .receipts
            .iter()
            .find(|r| r.sequence == sequence)
        {
            if r.fingerprint == hash {
                return Ok(Json(json!(r)));
            }
            return Err((StatusCode::CONFLICT, "重复序号内容不同".into()));
        }
        i.scheduler.source(&id).unwrap().fit.clone()
    };
    let data = bytes.to_vec();
    let png = tokio::task::spawn_blocking(move || normalize(&data, &fit))
        .await
        .map_err(bad)?
        .map_err(bad)?;
    let mut i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    let r = publish(&mut i, &id, sequence, hash, png, &format, a.now())?;
    Ok(Json(json!(r)))
}
async fn receipt(
    State(a): State<Arc<App>>,
    Path((id, seq)): Path<(String, u64)>,
    h: HeaderMap,
) -> ApiResult {
    let i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    let r = i.external[&id]
        .receipts
        .iter()
        .find(|r| r.sequence == seq)
        .ok_or((StatusCode::NOT_FOUND, "回执不存在或已超出保留窗口".into()))?;
    Ok(Json(json!(r)))
}
async fn sound(
    State(a): State<Arc<App>>,
    Path((id, sequence)): Path<(String, u64)>,
    h: HeaderMap,
    bytes: Bytes,
) -> ApiResult {
    let mut i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    let volume = match h.get("x-audio-volume") {
        None => 90,
        Some(v) => v
            .to_str()
            .ok()
            .and_then(|s| s.parse::<u8>().ok())
            .filter(|v| *v <= 100)
            .ok_or_else(|| bad("音量必须为 0～100"))?,
    };
    let clip = audio::decode(&bytes).map_err(bad)?;
    let hash = fingerprint(&bytes, &volume.to_string());
    let receipt = i.external[&id]
        .receipts
        .iter()
        .find(|r| r.sequence == sequence)
        .ok_or((StatusCode::NOT_FOUND, "画面回执不存在".into()))?;
    let revision = receipt.revision;
    if let Some(old) = receipt.audio_fingerprint {
        if old != hash {
            return Err((StatusCode::CONFLICT, "同一画面只能附加一条提示音".into()));
        }
    } else {
        queue_audio(&mut i, &id, revision, clip, volume, a.now())?;
        i.external
            .get_mut(&id)
            .unwrap()
            .receipts
            .iter_mut()
            .find(|r| r.sequence == sequence)
            .unwrap()
            .audio_fingerprint = Some(hash);
    }
    Ok(Json(
        json!({"sequence":sequence,"revision":revision,"state":"accepted","semantics":"accepted_by_scheduler"}),
    ))
}
#[derive(Deserialize)]
struct CursorQuery {
    #[serde(default)]
    after: u64,
}
async fn events(
    State(a): State<Arc<App>>,
    Path(id): Path<String>,
    Query(q): Query<CursorQuery>,
    h: HeaderMap,
) -> ApiResult {
    let i = a.inner.lock().await;
    authorize(&i, &id, &h, a.now())?;
    let s = &i.external[&id];
    let gap = s
        .events
        .front()
        .is_some_and(|e| e["cursor"].as_u64().unwrap() > q.after.saturating_add(1));
    Ok(Json(
        json!({"cursor":s.event_serial,"gap":gap,"events":s.events.iter().filter(|e|e["cursor"].as_u64().unwrap()>q.after).collect::<Vec<_>>()}),
    ))
}
pub fn router(a: Arc<App>) -> Router {
    Router::new()
        .route("/v1/sessions", post(open))
        .route("/v1/sessions/{id}", delete(close))
        .route("/v1/sessions/{id}/heartbeat", post(heartbeat))
        .route(
            "/v1/sessions/{id}/frames/{sequence}",
            post(frame).get(receipt),
        )
        .route("/v1/sessions/{id}/events", get(events))
        .route(
            "/v1/sessions/{id}/frames/{sequence}/audio",
            post(sound).layer(DefaultBodyLimit::max(98304)),
        )
        .layer(DefaultBodyLimit::max(8 * 1024 * 1024))
        .with_state(a)
}

struct Peer {
    connection: u64,
    id: Option<String>,
    created: u64,
    palette: [u8; 20],
    image: Option<IncomingImage>,
    last_image: u32,
    last_result: u8,
    control: u32,
    last_ping: u32,
    key_ack: u64,
    last_key_send: u64,
    connect_name: String,
    audio: Option<IncomingAudio>,
}
impl Peer {
    fn new(now: u64, palette: [u8; 20]) -> Self {
        Self {
            connection: (uuid::Uuid::new_v4().as_u128() as u64).max(1),
            id: None,
            created: now,
            palette,
            image: None,
            last_image: 0,
            last_result: 0,
            control: 0,
            last_ping: 0,
            key_ack: 0,
            last_key_send: 0,
            connect_name: String::new(),
            audio: None,
        }
    }
}
pub async fn udp(a: Arc<App>, socket: Arc<tokio::net::UdpSocket>) {
    let mut peers: HashMap<SocketAddr, Peer> = HashMap::new();
    let mut buffer = [0; 1201];
    let mut tick = tokio::time::interval(Duration::from_millis(250));
    loop {
        tokio::select! {
         _=tick.tick()=>{
          let now=a.now();let i=a.inner.lock().await;peers.retain(|_,p|if let Some(id)=&p.id{i.external.contains_key(id)}else{now.saturating_sub(p.created)<15000});
          for (addr,p) in &mut peers {if now.saturating_sub(p.last_key_send)<500{continue}if let Some(s)=p.id.as_ref().and_then(|id|i.external.get(id)){for e in s.events.iter().filter(|e|e["cursor"].as_u64().unwrap()>p.key_ack){let code=match e["key"].as_str(){Some("Up")=>1,Some("Down")=>2,_=>3};let action=if e["action"]=="Long"{2}else{1};if code==3&&action==2{continue}let packet=Packet{kind:14,connection:p.connection,sequence:e["cursor"].as_u64().unwrap() as u32,body:vec![code,action]};let _=socket.send_to(&packet.encode(),addr).await;}p.last_key_send=now;}}
         },
         received=socket.recv_from(&mut buffer)=>{
          // Windows reports ICMP from a departed UDP client on the shared socket.
          // One producer closing must not terminate reception for every producer.
          let (n,addr)=match received{Ok(value)=>value,Err(e) if matches!(e.kind(),std::io::ErrorKind::ConnectionReset|std::io::ErrorKind::ConnectionRefused|std::io::ErrorKind::Interrupted|std::io::ErrorKind::WouldBlock)=>continue,Err(e)=>{log(&mut *a.inner.lock().await,a.now(),format!("SDK 接收入口已停止：{e}"));break;}};
          let Some(mut packet)=Packet::decode(&buffer[..n])else{continue};let now=a.now();
          if packet.kind==1&&packet.body.is_empty(){let i=a.inner.lock().await;let stale=peers.get(&addr).is_some_and(|p|match &p.id{Some(id)=>!i.external.contains_key(id),None=>p.control>0});if stale{peers.remove(&addr);}drop(i);if !peers.contains_key(&addr){if peers.len()>=64{continue}let i=a.inner.lock().await;let palette=if let Some(d)=&i.device{let mut p=[0;20];p[..4].copy_from_slice(&d.palette().gray4);p[4..].copy_from_slice(&d.palette().gray16);p}else{uniform_palette()};peers.insert(addr,Peer::new(now,palette));}}
          let Some(p)=peers.get_mut(&addr)else{continue};if packet.kind!=1&&packet.connection!=p.connection{continue}packet.connection=p.connection;
          if packet.kind==142 {if packet.body==[0]{p.key_ack=p.key_ack.max(packet.sequence as u64);}continue}if packet.kind&128!=0{continue}
          let mut body=vec![0];
          if packet.kind==1 {
           if !packet.body.is_empty(){continue}body.extend([0,12]);body.extend(b"00000000abcd");body.push(19);body.extend(b"Scheduler (managed)");body.extend([1,144,1,44,0,0,0,0,0,0,0,0]);
          } else if packet.kind==2 {
           if packet.body.first().copied().map(|n|n as usize+1)!=Some(packet.body.len())||packet.body.len()<2||packet.body.len()>49{body[0]=2;}
           else if let Ok(name)=std::str::from_utf8(&packet.body[1..]){if p.id.is_none(){let mut i=a.inner.lock().await;match register(&mut i,name,"sdk",now){Ok(id)=>{p.id=Some(id);p.control=packet.sequence;p.connect_name=name.into();},Err(_)=>body[0]=1}}else if name!=p.connect_name||packet.sequence!=p.control{body[0]=1;}}else{body[0]=2;}
          }else{
           let valid=if let Some(id)=&p.id{a.inner.lock().await.external.get(id).is_some_and(|s|now.saturating_sub(s.seen)<15000)}else{false};if !valid{body[0]=3;}
           else{match packet.kind{
            3 if packet.body.is_empty()=>{if packet.sequence>p.last_ping{p.last_ping=packet.sequence;if let Some(s)=a.inner.lock().await.external.get_mut(p.id.as_ref().unwrap()){s.seen=now;}}},
            4 if packet.body.len()==1=>{let id=p.id.take().unwrap();remove(&mut *a.inner.lock().await,&id);},
            16 if packet.body.is_empty()=>body.extend(p.palette),
            15 if packet.body.is_empty()=>{body.extend([255,255,127]);},
            5 if packet.body.len()==3=>{let bpp=packet.body[0];let size=u16::from_be_bytes([packet.body[1],packet.body[2]])as usize;if let Some(img)=&p.image{if img.id==packet.sequence{if img.bpp!=bpp||img.size!=size{body[0]=2;}}else if packet.sequence<=p.control{body[0]=2;}else{match IncomingImage::new(packet.sequence,bpp,size){Ok(img)=>{p.image=Some(img);p.control=packet.sequence},Err(_)=>body[0]=2}}}else if packet.sequence<=p.control{body[0]=2;}else{match IncomingImage::new(packet.sequence,bpp,size){Ok(img)=>{p.image=Some(img);p.control=packet.sequence},Err(_)=>body[0]=2}}},
            6=>{if packet.body.len()<5{continue}let id=u32::from_be_bytes(packet.body[..4].try_into().unwrap());if let Some(img)=&mut p.image{if img.id==id{let _=img.chunk(packet.sequence,&packet.body[4..]);}}continue;},
            7 if packet.body.len()==4=>{let requested=u32::from_be_bytes(packet.body[..4].try_into().unwrap());if let Some(img)=&mut p.image{if img.id!=requested{body[0]=2;}else{
              if img.state==1&&img.complete(){match img.decode(&p.palette){Ok(pixels)=>{let gray=image::GrayImage::from_raw(400,300,pixels).unwrap();let mut out=Cursor::new(vec![]);let result=image::DynamicImage::ImageLuma8(gray).write_to(&mut out,image::ImageFormat::Png);if result.is_ok(){let format=match img.bpp{2=>"gray4",4=>"gray16",_=>"mono"};let bytes=out.into_inner();let hash=fingerprint(&bytes,format);let mut i=a.inner.lock().await;if publish(&mut i,p.id.as_ref().unwrap(),img.id as u64,hash,bytes,format,now).is_ok(){img.state=3;}else{img.state=4;}}else{img.state=4;}},Err(_)=>img.state=4}p.last_image=img.id;p.last_result=if img.state==3{0}else{7};}
              body.push(img.state);body.extend(img.bitmap.to_be_bytes());
            }}else{body[0]=2;}},
            8 if packet.body.len()==1=>{
              let volume=packet.body[0];
              if let Some(sound)=p.audio.as_ref().filter(|s|s.id==packet.sequence){if sound.volume!=volume{body[0]=2;}}
              else if volume>100||packet.sequence<=p.control{body[0]=2;}
              else{let i=a.inner.lock().await;let source=i.scheduler.source(p.id.as_ref().unwrap());
                if i.blocked||i.focus_unknown||i.recording||i.scheduler.paused||(i.mode=="device"&&i.device.is_none())||!source.is_some_and(|s|s.valid(now)){body[0]=1;}
                else{p.audio=Some(IncomingAudio::new(packet.sequence,volume,source.unwrap().revision,i.media_epoch));p.control=packet.sequence;}}
            },
            9=>{if packet.body.len()>=5{let id=u32::from_be_bytes(packet.body[..4].try_into().unwrap());if let Some(sound)=p.audio.as_mut().filter(|s|s.id==id){sound.chunk(packet.sequence,&packet.body[4..]);}}continue;},
            10 if packet.body.len()==11=>{
              let id=u32::from_be_bytes(packet.body[..4].try_into().unwrap());let total=u32::from_be_bytes(packet.body[4..8].try_into().unwrap());let tail=u16::from_be_bytes(packet.body[8..10].try_into().unwrap());
              if let Some(sound)=p.audio.as_mut().filter(|s|s.id==id){
                if packet.body[10]!=0||sound.end.is_some_and(|end|end!=(total,tail)){body[0]=2;}
                else if sound.end.is_none(){
                  let mut i=a.inner.lock().await;
                  let accepted=if sound.epoch!=i.media_epoch{false}else{sound.finish(total,tail).ok().is_some_and(|clip|queue_audio(&mut i,p.id.as_ref().unwrap(),sound.revision,clip,sound.volume,now).is_ok())};
                  sound.end=Some((total,tail));sound.result=Some(if accepted{0}else{7});p.control=p.control.max(packet.sequence);
                }
              }else{body[0]=2;}
            },
            11 if packet.body.len()==4=>{
              let id=u32::from_be_bytes(packet.body[..4].try_into().unwrap());
              if let Some(sound)=p.audio.as_mut().filter(|s|s.id==id){
                a.inner.lock().await.audio_pending.retain(|s|!(Some(&s.source)==p.id.as_ref()&&s.revision==sound.revision));
                sound.result=Some(4);sound.end.get_or_insert((0,0));
              }else{body[0]=2;}
            },
            12 if packet.body.is_empty()=>{let (id,bitmap,state)=p.image.as_ref().map(|m|(m.id,m.bitmap,m.state)).unwrap_or((0,0,0));body.extend([2,state,0]);body.extend(id.to_be_bytes());body.extend(bitmap.to_be_bytes());body.extend(0u32.to_be_bytes());body.extend(p.last_image.to_be_bytes());body.push(p.last_result);let (audio_id,audio_result)=p.audio.as_ref().filter(|s|s.result.is_some()).map(|s|(s.id,s.result.unwrap())).unwrap_or((0,0));body.extend(audio_id.to_be_bytes());body.push(audio_result);},
            _=>body[0]=2,
           }}
          }
          let _=socket.send_to(&packet.reply(body).encode(),addr).await;
         }
        }
    }
}
