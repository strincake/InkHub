use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Boost {
    pub priority: u8,
    pub until: Option<u64>,
    pub until_replaced: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Source {
    pub id: String,
    pub name: String,
    pub priority: u8,
    pub min_ms: u64,
    pub hold_ms: u64,
    pub ttl_ms: u64,
    pub persistent: bool,
    pub bypass: bool,
    pub enabled: bool,
    pub format: String,
    #[serde(default)]
    pub format_override: bool,
    pub fit: String,
    pub boost: Option<Boost>,
    pub revision: u64,
    pub updated_at: u64,
    pub order: u64,
    pub consumed: u64,
}
impl Source {
    pub fn new(id: String, name: String, priority: u8) -> Self {
        Self {
            id,
            name,
            priority,
            min_ms: 5000,
            hold_ms: 30000,
            ttl_ms: 120000,
            persistent: false,
            bypass: false,
            enabled: true,
            format: "mono".into(),
            format_override: false,
            fit: "contain".into(),
            boost: None,
            revision: 0,
            updated_at: 0,
            order: 0,
            consumed: 0,
        }
    }
    pub fn effective(&self, now: u64) -> u8 {
        self.boost
            .as_ref()
            .filter(|b| b.until.is_none_or(|t| now < t))
            .map_or(self.priority, |b| b.priority)
    }
    pub fn valid(&self, now: u64) -> bool {
        self.enabled
            && self.revision > 0
            && (self.ttl_ms == 0 || now.saturating_sub(self.updated_at) < self.ttl_ms)
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Frame {
    pub id: String,
    pub revision: u64,
}
#[derive(Clone, Debug, Serialize)]
pub struct Display {
    pub frame: Frame,
    pub entered_at: u64,
    pub shown_at: u64,
    pub yielded: bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct Scheduler {
    pub sources: Vec<Source>,
    pub current: Option<Display>,
    pub preempt: bool,
    pub paused: bool,
    pub serial: u64,
}
impl Default for Scheduler {
    fn default() -> Self {
        Self {
            sources: vec![],
            current: None,
            preempt: true,
            paused: false,
            serial: 0,
        }
    }
}
impl Scheduler {
    pub fn add(&mut self, source: Source) {
        self.sources.push(source);
    }
    pub fn source(&self, id: &str) -> Option<&Source> {
        self.sources.iter().find(|s| s.id == id)
    }
    pub fn source_mut(&mut self, id: &str) -> Option<&mut Source> {
        self.sources.iter_mut().find(|s| s.id == id)
    }
    pub fn update(&mut self, id: &str, now: u64) -> Result<(), String> {
        self.serial += 1;
        let order = self.serial;
        let s = self.source_mut(id).ok_or("来源不存在")?;
        s.revision += 1;
        s.updated_at = now;
        s.order = order;
        Ok(())
    }
    pub fn remove(&mut self, id: &str) {
        self.sources.retain(|s| s.id != id);
        if self.current.as_ref().is_some_and(|d| d.frame.id == id) {
            self.current = None;
        }
    }
    pub fn next(&mut self, now: u64) -> Option<Frame> {
        if self.paused {
            return None;
        }
        let active = self.current.as_ref().and_then(|d| {
            self.source(&d.frame.id)
                .filter(|s| s.valid(now))
                .map(|s| (d.clone(), s.clone()))
        });
        let mut released = active.is_none();
        let mut own_update = None;
        if let Some((d, s)) = &active {
            // A fresh state from the foreground source is not a source switch.
            if s.revision != d.frame.revision {
                own_update = Some(Frame {
                    id: s.id.clone(),
                    revision: s.revision,
                });
            }
            released = own_update.is_none()
                && (d.yielded
                    || (s.hold_ms > 0
                        && now.saturating_sub(d.shown_at) >= s.hold_ms
                        && now.saturating_sub(d.entered_at) >= s.min_ms));
            if released {
                if let Some(d) = &mut self.current {
                    d.yielded = true;
                }
            }
        }
        let mut candidates: Vec<_> = self
            .sources
            .iter()
            .filter(|s| s.valid(now))
            .filter(|s| {
                if let Some((d, _)) = &active {
                    if d.frame.id == s.id {
                        return false;
                    }
                }
                s.revision > s.consumed || (released && s.persistent)
            })
            .collect();
        candidates.sort_by_key(|s| (s.effective(now), std::cmp::Reverse(s.order)));
        for s in candidates {
            if !released {
                let (d, old) = active.as_ref()?;
                let p = s.effective(now);
                let q = old.effective(now);
                let allowed = (p < q && self.preempt) || (p == q && s.order > old.order);
                if !allowed || (!s.bypass && now.saturating_sub(d.entered_at) < old.min_ms) {
                    continue;
                }
            }
            return Some(Frame {
                id: s.id.clone(),
                revision: s.revision,
            });
        }
        own_update
    }
    pub fn complete(&mut self, frame: Frame, now: u64) {
        if !self.source(&frame.id).is_some_and(|s| s.valid(now)) {
            // The physical image changed even if its producer left during refresh.
            self.current = None;
            return;
        }
        let same = self
            .current
            .as_ref()
            .is_some_and(|d| d.frame.id == frame.id);
        let entered_at = if same {
            self.current.as_ref().unwrap().entered_at
        } else {
            now
        };
        if !same {
            if let Some(old) = self.current.as_ref().map(|d| d.frame.id.clone()) {
                if let Some(s) = self.source_mut(&old) {
                    if s.boost.as_ref().is_some_and(|b| b.until_replaced) {
                        s.boost = None;
                    }
                }
            }
        }
        if let Some(s) = self.source_mut(&frame.id) {
            s.consumed = s.consumed.max(frame.revision);
        }
        self.current = Some(Display {
            frame,
            entered_at,
            shown_at: now,
            yielded: false,
        });
    }
    pub fn key_target(&self, now: u64) -> Option<String> {
        let d = self.current.as_ref()?;
        self.source(&d.frame.id)
            .filter(|s| s.valid(now))
            .map(|s| s.id.clone())
    }
    pub fn reason(&self, id: &str, now: u64) -> String {
        let Some(s) = self.source(id) else {
            return "来源已退出".into();
        };
        if !s.enabled {
            return "已暂停此来源".into();
        }
        if s.revision == 0 {
            return "等待第一张画面".into();
        }
        if !s.valid(now) {
            return "任务已到期，等待新画面".into();
        }
        if self.current.as_ref().is_some_and(|d| d.frame.id == id) {
            return "屏幕当前画面".into();
        }
        if self.paused {
            return "自动切换已暂停".into();
        }
        if s.revision <= s.consumed && !s.persistent {
            return "已展示，等待新内容".into();
        }
        if let Some(d) = &self.current {
            if let Some(old) = self.source(&d.frame.id).filter(|s| s.valid(now)) {
                if d.yielded {
                    return "保留画面，可在空闲时返回".into();
                }
                if s.effective(now) < old.effective(now) && !self.preempt {
                    return "已关闭高优先级提前切入".into();
                }
                if s.effective(now) > old.effective(now) {
                    return "等待当前来源让出屏幕".into();
                }
                if !s.bypass && now.saturating_sub(d.entered_at) < old.min_ms {
                    return format!(
                        "当前内容还需显示 {} 秒",
                        (old.min_ms - now.saturating_sub(d.entered_at)).div_ceil(1000)
                    );
                }
            }
        }
        "等待调度 / 空闲时可返回".into()
    }
}
