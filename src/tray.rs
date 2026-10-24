//! Native Windows notification-area icon. All Win32 resources stay on its UI thread.
use std::{
    mem::size_of,
    os::windows::ffi::OsStrExt,
    path::Path,
    ptr::{null, null_mut},
    sync::{Arc, Mutex},
    thread::{self, JoinHandle},
};
use tokio::sync::mpsc::UnboundedSender;
use windows_sys::Win32::{
    Foundation::*,
    System::LibraryLoader::GetModuleHandleW,
    UI::{Shell::*, WindowsAndMessaging::*},
};

pub const OPEN: usize = 1001;
pub const EXIT: usize = 1002;
const CALLBACK: u32 = WM_APP + 1;
const TIMER: usize = 1;

pub enum Command {
    Open,
    Exit,
}
pub struct Tray {
    hwnd: usize,
    thread: Option<JoinHandle<()>>,
}

impl Tray {
    pub fn start(
        status: Arc<Mutex<String>>,
        commands: UnboundedSender<Command>,
        icon: &Path,
    ) -> Result<Self, String> {
        let icon = icon.to_path_buf();
        let (ready_tx, ready_rx) = std::sync::mpsc::sync_channel(1);
        let thread = thread::Builder::new()
            .name("inkhub-tray".into())
            .spawn(move || unsafe {
                let class = wide("InkHubTrayWindow");
                let instance = GetModuleHandleW(null());
                let wc = WNDCLASSW {
                    lpfnWndProc: Some(window_proc),
                    hInstance: instance,
                    lpszClassName: class.as_ptr(),
                    ..std::mem::zeroed()
                };
                let atom = RegisterClassW(&wc);
                if atom == 0 && GetLastError() != ERROR_CLASS_ALREADY_EXISTS {
                    let _ =
                        ready_tx.send(Err(format!("RegisterClassW failed: {}", GetLastError())));
                    return;
                }
                let path: Vec<u16> = icon.as_os_str().encode_wide().chain(Some(0)).collect();
                let loaded = LoadImageW(
                    null_mut(),
                    path.as_ptr(),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                );
                let owned_icon = !loaded.is_null();
                let icon = if owned_icon {
                    loaded
                } else {
                    LoadIconW(null_mut(), IDI_APPLICATION)
                };
                let state = Box::new(State {
                    status,
                    commands,
                    icon,
                    taskbar_created: RegisterWindowMessageW(wide("TaskbarCreated").as_ptr()),
                });
                // The box outlives the window and every callback, including failed creation.
                let hwnd = CreateWindowExW(
                    0,
                    class.as_ptr(),
                    class.as_ptr(),
                    WS_OVERLAPPED,
                    0,
                    0,
                    0,
                    0,
                    null_mut(),
                    null_mut(),
                    instance,
                    (&*state as *const State).cast(),
                );
                if hwnd.is_null() {
                    let error = GetLastError();
                    if owned_icon {
                        DestroyIcon(icon);
                    }
                    if atom != 0 {
                        UnregisterClassW(class.as_ptr(), instance);
                    }
                    let _ = ready_tx.send(Err(format!("CreateWindowExW failed: {error}")));
                    return;
                }
                state.notify(hwnd, NIM_ADD);
                if SetTimer(hwnd, TIMER, 1000, None) == 0 {
                    DestroyWindow(hwnd);
                    if owned_icon {
                        DestroyIcon(icon);
                    }
                    if atom != 0 {
                        UnregisterClassW(class.as_ptr(), instance);
                    }
                    let _ = ready_tx.send(Err("Could not start tray status timer".into()));
                    return;
                }
                if ready_tx.send(Ok(hwnd as usize)).is_err() {
                    DestroyWindow(hwnd);
                }
                let mut msg: MSG = std::mem::zeroed();
                loop {
                    let result = GetMessageW(&mut msg, null_mut(), 0, 0);
                    if result <= 0 {
                        break;
                    }
                    TranslateMessage(&msg);
                    DispatchMessageW(&msg);
                }
                if IsWindow(hwnd) != 0 {
                    DestroyWindow(hwnd);
                }
                if owned_icon {
                    DestroyIcon(icon);
                }
                if atom != 0 {
                    UnregisterClassW(class.as_ptr(), instance);
                }
            })
            .map_err(|e| format!("Could not start tray thread: {e}"))?;
        match ready_rx.recv() {
            Ok(Ok(hwnd)) => Ok(Self {
                hwnd,
                thread: Some(thread),
            }),
            result => {
                let _ = thread.join();
                Err(match result {
                    Ok(Err(error)) => error,
                    _ => "Tray thread stopped during startup".into(),
                })
            }
        }
    }
}
impl Drop for Tray {
    fn drop(&mut self) {
        unsafe {
            PostMessageW(self.hwnd as HWND, WM_CLOSE, 0, 0);
        }
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}
struct State {
    status: Arc<Mutex<String>>,
    commands: UnboundedSender<Command>,
    icon: HICON,
    taskbar_created: u32,
}
impl State {
    fn status(&self) -> String {
        self.status
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }
    unsafe fn notify(&self, hwnd: HWND, action: NOTIFY_ICON_MESSAGE) -> bool {
        let mut data: NOTIFYICONDATAW = std::mem::zeroed();
        data.cbSize = size_of::<NOTIFYICONDATAW>() as u32;
        data.hWnd = hwnd;
        data.uID = 1;
        // Keep the legacy callback version: lParam is the complete mouse message.
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        data.uCallbackMessage = CALLBACK;
        data.hIcon = self.icon;
        // Reserve the final UTF-16 unit for NUL, without splitting a surrogate pair.
        let tip = wide(&format!("InkHub · {}", self.status()));
        let mut count = tip.len().saturating_sub(1).min(data.szTip.len() - 1);
        if count > 0 && (0xD800..=0xDBFF).contains(&tip[count - 1]) {
            count -= 1;
        }
        data.szTip[..count].copy_from_slice(&tip[..count]);
        Shell_NotifyIconW(action, &data) != 0
    }
    unsafe fn menu(&self, hwnd: HWND) {
        let menu = CreatePopupMenu();
        if menu.is_null() {
            return;
        }
        let status = wide(&self.status().replace('&', "&&"));
        AppendMenuW(
            menu,
            MF_STRING | MF_DISABLED | MF_GRAYED,
            0,
            status.as_ptr(),
        );
        AppendMenuW(menu, MF_SEPARATOR, 0, null());
        AppendMenuW(menu, MF_STRING, OPEN, wide("打开管理界面").as_ptr());
        AppendMenuW(menu, MF_STRING, EXIT, wide("退出墨枢").as_ptr());
        SetMenuDefaultItem(menu, OPEN as u32, 0);
        let mut point: POINT = std::mem::zeroed();
        GetCursorPos(&mut point);
        SetForegroundWindow(hwnd);
        let chosen = TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            hwnd,
            null(),
        );
        DestroyMenu(menu);
        PostMessageW(hwnd, WM_NULL, 0, 0);
        self.notify(hwnd, NIM_SETFOCUS);
        self.command(chosen as usize);
    }
    fn command(&self, id: usize) {
        let command = match id {
            OPEN => Command::Open,
            EXIT => Command::Exit,
            _ => return,
        };
        let _ = self.commands.send(command);
    }
}
unsafe extern "system" fn window_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if message == WM_NCCREATE {
        let create = &*(lparam as *const CREATESTRUCTW);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, create.lpCreateParams as isize);
    }
    let pointer = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const State;
    if !pointer.is_null() {
        let state = &*pointer;
        if state.taskbar_created != 0 && message == state.taskbar_created {
            state.notify(hwnd, NIM_ADD);
            return 0;
        }
        match message {
            WM_TIMER if wparam == TIMER => {
                if !state.notify(hwnd, NIM_MODIFY) {
                    state.notify(hwnd, NIM_ADD);
                }
                return 0;
            }
            WM_COMMAND => {
                state.command(wparam & 0xffff);
                return 0;
            }
            CALLBACK => {
                match lparam as u32 {
                    WM_LBUTTONDBLCLK => state.command(OPEN),
                    WM_RBUTTONUP | WM_CONTEXTMENU => state.menu(hwnd),
                    _ => {}
                }
                return 0;
            }
            WM_CLOSE => {
                state.command(EXIT);
                DestroyWindow(hwnd);
                return 0;
            }
            WM_ENDSESSION if wparam != 0 => {
                state.command(EXIT);
                DestroyWindow(hwnd);
                return 0;
            }
            WM_DESTROY => {
                KillTimer(hwnd, TIMER);
                state.notify(hwnd, NIM_DELETE);
                PostQuitMessage(0);
                return 0;
            }
            WM_NCDESTROY => {
                SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            }
            _ => {}
        }
    }
    DefWindowProcW(hwnd, message, wparam, lparam)
}
fn wide(value: &str) -> Vec<u16> {
    value
        .encode_utf16()
        .map(|c| if c == 0 { 32 } else { c })
        .chain(Some(0))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_commands_reach_host_and_drop_removes_window() {
        let (sender, mut receiver) = tokio::sync::mpsc::unbounded_channel();
        let status = Arc::new(Mutex::new("模拟屏幕".to_string()));
        let tray = Tray::start(status.clone(), sender, Path::new("missing-test-icon.ico")).unwrap();
        let hwnd = tray.hwnd as HWND;
        unsafe {
            SendMessageW(hwnd, WM_COMMAND, OPEN, 0);
        }
        assert!(matches!(receiver.try_recv(), Ok(Command::Open)));
        *status.lock().unwrap() = "设备已连接".into();
        unsafe {
            SendMessageW(hwnd, WM_TIMER, TIMER, 0);
            SendMessageW(hwnd, WM_COMMAND, EXIT, 0);
        }
        assert!(matches!(receiver.try_recv(), Ok(Command::Exit)));
        drop(tray);
        assert_eq!(unsafe { IsWindow(hwnd) }, 0);
    }
}
