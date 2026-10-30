//! Bounded, local runtime history. Never serialize settings or credentials here.
use std::{io::Write, path::PathBuf, sync::{Mutex, OnceLock}, time::{SystemTime, UNIX_EPOCH}};

static FILE: OnceLock<Mutex<PathBuf>> = OnceLock::new();
const LIMIT: u64 = 2 * 1024 * 1024;

pub fn init(config: &std::path::Path) -> std::io::Result<()> {
    let folder = config.parent().unwrap_or_else(|| std::path::Path::new(".")).join("logs");
    std::fs::create_dir_all(&folder)?;
    let path = folder.join("runtime.log");
    std::fs::OpenOptions::new().create(true).append(true).open(&path)?;
    let _ = FILE.set(Mutex::new(path));
    record(0, "宿主启动", "");
    Ok(())
}

pub fn record(elapsed_ms: u64, message: &str, context: &str) {
    let Some(file) = FILE.get() else { return };
    let path = file.lock().unwrap_or_else(|e| e.into_inner());
    let result = (|| -> std::io::Result<()> {
        if std::fs::metadata(&*path)?.len() >= LIMIT {
            let backup = path.with_file_name("runtime.previous.log");
            if backup.exists() { std::fs::remove_file(&backup)?; }
            std::fs::rename(&*path, backup)?;
        }
        let mut output = std::fs::OpenOptions::new().create(true).append(true).open(&*path)?;
        let entry = serde_json::json!({
            "unix_ms": SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64,
            "pid": std::process::id(), "elapsed_ms": elapsed_ms,
            "message": message, "context": context,
        });
        writeln!(output, "{entry}")
    })();
    if let Err(error) = result { eprintln!("运行日志写入失败：{error}"); }
}
