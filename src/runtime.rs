//! Installed resources are read-only; settings stay in the current user's profile.
use std::{path::PathBuf, sync::OnceLock};

pub struct Layout {
    pub root: PathBuf,
    user: Option<PathBuf>,
}
impl Layout {
    pub fn new(root: PathBuf, user: Option<PathBuf>) -> Self {
        Self { root, user }
    }
    pub fn packaged(&self) -> bool {
        self.user.is_some()
    }
    pub fn script(&self, name: &str) -> PathBuf {
        self.root.join("python").join(name)
    }
    pub fn python(&self) -> PathBuf {
        if self.packaged() {
            self.root.join("runtime/python/python.exe")
        } else {
            PathBuf::from("python")
        }
    }
    pub fn config(&self) -> PathBuf {
        self.user
            .as_ref()
            .map(|p| p.join("InkHub/settings.json"))
            .unwrap_or_else(|| self.root.join("settings.json"))
    }
}
pub fn layout() -> &'static Layout {
    static LAYOUT: OnceLock<Layout> = OnceLock::new();
    LAYOUT.get_or_init(|| {
        let folder = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_default();
        if folder.join("runtime-layout.json").is_file() {
            Layout::new(
                folder,
                Some(
                    std::env::var_os("LOCALAPPDATA")
                        .map(PathBuf::from)
                        .unwrap_or_else(std::env::temp_dir),
                ),
            )
        } else {
            Layout::new(PathBuf::from(env!("CARGO_MANIFEST_DIR")), None)
        }
    })
}
pub fn flag(name: &str) -> bool {
    std::env::args().any(|arg| arg == name)
}
pub fn wants_tray() -> bool {
    cfg!(windows) && !flag("--no-tray") && (layout().packaged() || flag("--tray"))
}
pub fn wants_browser() -> bool {
    !flag("--no-browser") && !flag("--autostart") && (layout().packaged() || flag("--open-browser"))
}
#[cfg(windows)]
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(Some(0)).collect()
}
pub fn open_browser(url: &str) {
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::UI::Shell::ShellExecuteW;
        ShellExecuteW(
            std::ptr::null_mut(),
            wide("open").as_ptr(),
            wide(url).as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        );
    }
    #[cfg(not(windows))]
    {
        let _ = std::process::Command::new("xdg-open").arg(url).spawn();
    }
}
pub fn autostart_supported() -> bool {
    cfg!(windows) && layout().packaged()
}
#[cfg(windows)]
fn startup_command() -> String {
    format!(
        "\"{}\" --autostart",
        std::env::current_exe().unwrap_or_default().display()
    )
}
#[cfg(windows)]
pub fn autostart_enabled() -> bool {
    if !autostart_supported() {
        return false;
    }
    use windows_sys::Win32::System::Registry::*;
    let mut buffer = vec![0u16; 32768];
    let mut size = (buffer.len() * 2) as u32;
    let result = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            wide(r"Software\Microsoft\Windows\CurrentVersion\Run").as_ptr(),
            wide("InkHub").as_ptr(),
            RRF_RT_REG_SZ,
            std::ptr::null_mut(),
            buffer.as_mut_ptr().cast(),
            &mut size,
        )
    };
    if result != 0 {
        return false;
    }
    String::from_utf16_lossy(&buffer[..buffer.iter().position(|c| *c == 0).unwrap_or(buffer.len())])
        == startup_command()
}
#[cfg(not(windows))]
pub fn autostart_enabled() -> bool {
    false
}
pub fn set_autostart(enabled: bool) -> Result<(), String> {
    if !autostart_supported() {
        return Err("开机自启仅在 Windows 安装版中可用".into());
    }
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::System::Registry::*;
        let mut key = std::ptr::null_mut();
        let result = RegCreateKeyExW(
            HKEY_CURRENT_USER,
            wide(r"Software\Microsoft\Windows\CurrentVersion\Run").as_ptr(),
            0,
            std::ptr::null(),
            0,
            KEY_SET_VALUE,
            std::ptr::null(),
            &mut key,
            std::ptr::null_mut(),
        );
        if result != 0 {
            return Err(format!("无法打开当前用户启动设置：{result}"));
        }
        let result = if enabled {
            let command = wide(&startup_command());
            RegSetValueExW(
                key,
                wide("InkHub").as_ptr(),
                0,
                REG_SZ,
                command.as_ptr().cast(),
                (command.len() * 2) as u32,
            )
        } else {
            RegDeleteValueW(key, wide("InkHub").as_ptr())
        };
        RegCloseKey(key);
        if result != 0 && !(result == 2 && !enabled) {
            return Err(format!("无法保存开机自启设置：{result}"));
        }
    }
    Ok(())
}
pub fn report_error(error: &str) {
    eprintln!("{error}");
    if !layout().packaged() {
        return;
    }
    if let Some(parent) = layout().config().parent() {
        let logs = parent.join("logs");
        let _ = std::fs::create_dir_all(&logs);
        use std::io::Write;
        if let Ok(mut file) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("startup.log"))
        {
            let _ = writeln!(file, "{error}");
        }
    }
    #[cfg(windows)]
    if !flag("--no-browser") && !flag("--autostart") {
        unsafe {
            windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
                std::ptr::null_mut(),
                wide(error).as_ptr(),
                wide("墨枢启动失败").as_ptr(),
                0x10,
            );
        }
    }
}
pub async fn existing_instance(port: u16) -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    if port == 0 {
        return false;
    }
    tokio::time::timeout(std::time::Duration::from_secs(2),async {
        let mut stream=tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST,port)).await.ok()?;
        stream.write_all(format!("GET /control/state HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").as_bytes()).await.ok()?;
        let mut bytes=Vec::new();stream.take(1024*1024).read_to_end(&mut bytes).await.ok()?;
        let text=String::from_utf8_lossy(&bytes);let body=text.split_once("\r\n\r\n")?.1;
        let state:serde_json::Value=serde_json::from_str(body).ok()?;
        Some(state["device"]["mode"].is_string() && state["plugins"].is_array())
    }).await.ok().flatten().unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn packaged_layout_keeps_resources_and_user_data_separate() {
        let layout = Layout::new(PathBuf::from("app"), Some(PathBuf::from("user")));
        assert_eq!(
            layout.script("plugin_worker.py"),
            PathBuf::from("app/python/plugin_worker.py")
        );
        assert_eq!(
            layout.python(),
            PathBuf::from("app/runtime/python/python.exe")
        );
        assert_eq!(layout.config(), PathBuf::from("user/InkHub/settings.json"));
    }
    #[test]
    fn developer_layout_keeps_source_configuration() {
        let layout = Layout::new(PathBuf::from("source"), None);
        assert_eq!(layout.python(), PathBuf::from("python"));
        assert_eq!(layout.config(), PathBuf::from("source/settings.json"));
    }
}
