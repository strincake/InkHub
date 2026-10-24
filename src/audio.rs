//! Short, one-shot plugin sound requests; WAV is validated again at the host boundary.
use super::*;
#[derive(Clone)]
pub struct Pending {
    pub source: String,
    pub revision: u64,
    pub clip: zectrix_sdk::AudioClip,
    pub volume: u8,
}
pub fn decode(raw: &[u8]) -> Result<zectrix_sdk::AudioClip, String> {
    let fail = || "WAV 必须为完整 16 kHz 单声道 PCM16，最长 3 秒、96 KiB".to_string();
    if raw.len() < 44 || raw.len() > 98304 || &raw[..4] != b"RIFF" || &raw[8..12] != b"WAVE" {
        return Err(fail());
    }
    let u32at = |n| u32::from_le_bytes(raw[n..n + 4].try_into().unwrap()) as usize;
    if u32at(4) + 8 != raw.len() {
        return Err(fail());
    }
    let mut at = 12;
    let mut fmt = false;
    let mut data = None;
    while at + 8 <= raw.len() {
        let size = u32at(at + 4);
        let start = at + 8;
        let end = start
            .checked_add(size)
            .filter(|n| *n <= raw.len())
            .ok_or_else(fail)?;
        match &raw[at..at + 4] {
            b"fmt " => {
                if fmt || size < 16 {
                    return Err(fail());
                }
                let f = &raw[start..end];
                if f[..2] != [1, 0]
                    || f[2..4] != [1, 0]
                    || f[4..8] != 16000u32.to_le_bytes()
                    || f[8..12] != 32000u32.to_le_bytes()
                    || f[12..14] != [2, 0]
                    || f[14..16] != [16, 0]
                {
                    return Err(fail());
                }
                fmt = true;
            }
            b"data" => {
                if data.is_some() || size == 0 || size > 96000 || size % 2 != 0 {
                    return Err(fail());
                }
                data = Some(&raw[start..end]);
            }
            _ => {}
        }
        at = end + (size % 2);
    }
    if !fmt || at != raw.len() {
        return Err(fail());
    }
    Ok(zectrix_sdk::AudioClip {
        samples: data
            .ok_or_else(fail)?
            .chunks_exact(2)
            .map(|v| i16::from_le_bytes([v[0], v[1]]))
            .collect(),
    })
}
pub fn eligible(i: &Inner, p: &Pending, now: u64) -> bool {
    !i.blocked
        && !i.sending
        && !i.focus_unknown
        && !i.recording
        && !i.scheduler.paused
        && (i.mode != "device" || i.device.is_some())
        && i.scheduler
            .source(&p.source)
            .is_some_and(|s| s.valid(now) && s.revision == p.revision)
        && i.scheduler
            .current
            .as_ref()
            .is_some_and(|d| d.frame.id == p.source && d.frame.revision == p.revision)
}
pub async fn send(a: &Arc<App>) {
    let _operation = a.device_operation.lock().await;
    let job = {
        let mut i = a.inner.lock().await;
        let now = a.now();
        let index = i.audio_pending.iter().position(|p| eligible(&i, p, now));
        index.map(|n| {
            let p = i.audio_pending.remove(n);
            i.sending = true;
            i.audio_status = json!({"status":"playing","source":p.source,"revision":p.revision});
            (p, i.device.clone(), i.generation)
        })
    };
    let Some((p, device, generation)) = job else {
        return;
    };
    let result = if let Some(d) = device {
        d.play(&p.clip, p.volume)
            .await
            .map(|reason| format!("{reason:?}"))
    } else {
        Ok("simulated".into())
    };
    let mut i = a.inner.lock().await;
    if i.generation != generation {
        return;
    }
    i.sending = false;
    match result {
        Ok(reason) => {
            i.audio_status = json!({"status":if i.mode=="simulation"{"simulated"}else{"playback_ended"},"reason":reason,"source":p.source,"revision":p.revision});
        }
        Err(e) => {
            i.blocked = true;
            i.audio_pending.clear();
            if matches!(e, zectrix_sdk::Error::ResultUnknown) {
                i.focus_unknown = true;
            }
            i.audio_status = json!({"status":if matches!(e,zectrix_sdk::Error::ResultUnknown){"result_unknown"}else{"failed"},"error":e.to_string()});
            i.health = format!("音频发送暂停：{e}");
            log(&mut i, a.now(), format!("声音未自动重发：{e}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn wav(samples: usize) -> Vec<u8> {
        let mut out = b"RIFF".to_vec();
        out.extend(((36 + samples * 2) as u32).to_le_bytes());
        out.extend(b"WAVEfmt ");
        out.extend(16u32.to_le_bytes());
        out.extend([1, 0, 1, 0]);
        out.extend(16000u32.to_le_bytes());
        out.extend(32000u32.to_le_bytes());
        out.extend([2, 0, 16, 0]);
        out.extend(b"data");
        out.extend(((samples * 2) as u32).to_le_bytes());
        out.resize(44 + samples * 2, 0);
        out
    }
    fn inner() -> Inner {
        let mut scheduler = Scheduler::default();
        let mut source = Source::new("p".into(), "plugin".into(), 3);
        source.ttl_ms = 100;
        source.hold_ms = 0;
        scheduler.add(source);
        scheduler.update("p", 0).unwrap();
        scheduler.complete(
            Frame {
                id: "p".into(),
                revision: 1,
            },
            0,
        );
        Inner {
            scheduler,
            images: HashMap::new(),
            device: None,
            generation: 0,
            mode: "simulation".into(),
            target: String::new(),
            health: String::new(),
            blocked: false,
            connecting: false,
            reconnect: ReconnectSettings::default(),
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
            audio_status: Value::Null,
        }
    }
    #[test]
    fn validates_complete_short_pcm_wav() {
        assert_eq!(decode(&wav(48000)).unwrap().samples.len(), 48000);
        for raw in [wav(0), wav(48001), wav(4)[..50].to_vec()] {
            assert!(decode(&raw).is_err());
        }
        for (offset, byte) in [(20, 3), (22, 2), (24, 1), (28, 1), (32, 4), (34, 8)] {
            let mut raw = wav(4);
            raw[offset] = byte;
            assert!(decode(&raw).is_err());
        }
        let mut trailing = wav(4);
        trailing.push(0);
        assert!(decode(&trailing).is_err());
    }
    #[test]
    fn sounds_require_current_exact_valid_revision_and_media_permission() {
        let mut i = inner();
        let p = Pending {
            source: "p".into(),
            revision: 1,
            clip: decode(&wav(4)).unwrap(),
            volume: 90,
        };
        assert!(eligible(&i, &p, 1));
        assert!(!eligible(&i, &p, 100));
        i.blocked = true;
        assert!(!eligible(&i, &p, 1));
        i.blocked = false;
        i.recording = true;
        assert!(!eligible(&i, &p, 1));
        i.recording = false;
        i.sending = true;
        assert!(!eligible(&i, &p, 1));
        i.sending = false;
        i.focus_unknown = true;
        assert!(!eligible(&i, &p, 1));
        i.focus_unknown = false;
        i.scheduler.paused = true;
        assert!(!eligible(&i, &p, 1));
        i.scheduler.paused = false;
        i.mode = "device".into();
        assert!(!eligible(&i, &p, 1));
        i.mode = "simulation".into();
        i.scheduler.source_mut("p").unwrap().enabled = false;
        assert!(!eligible(&i, &p, 1));
        i.scheduler.source_mut("p").unwrap().enabled = true;
        i.scheduler.update("p", 1).unwrap();
        assert!(!eligible(&i, &p, 1));
        i.scheduler.current = None;
        assert!(!eligible(&i, &p, 1));
    }
}
