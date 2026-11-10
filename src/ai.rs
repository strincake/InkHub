//! Local AI authoring. Does not run, install or enable generated plugins.
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub async fn request(
    State(a): State<Arc<App>>,
    headers: HeaderMap,
    Json(mut body): Json<Value>,
) -> ApiResult {
    auth(&a, &headers)?;
    static SLOT: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
    let _slot = SLOT.try_acquire().map_err(|_| bad("已有 AI 请求正在处理，请等待完成"))?;
    if !body.is_object() || !matches!(body["op"].as_str(), Some("generate" | "tools" | "skill")) {
        return Err(bad("未知 AI 操作"));
    }
    const SKILL: &str = include_str!("../skills/inkhub-plugin/SKILL.md");
    const GUIDE: &str = include_str!("../docs/guides/plugin-development.md");
    body["instructions"] = json!(format!("{SKILL}\n\n{GUIDE}"));
    body["skill"] = json!(SKILL);
    body["guide"] = json!(GUIDE);
    let input = serde_json::to_vec(&body).map_err(bad)?;
    if input.len() > 250 * 1024 {
        return Err(bad("AI 请求过大"));
    }
    let mut command = tokio::process::Command::new(runtime::layout().python());
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command.arg(runtime::layout().script("ai_plugin.py"))
        .stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null()).kill_on_drop(true).spawn().map_err(|_| bad("无法启动 AI 连接进程，请检查 Python 运行环境"))?;
    let mut stdin = child.stdin.take().unwrap();
    let mut stdout = child.stdout.take().unwrap().take(16 * 1024 * 1024 + 1);
    let result = tokio::time::timeout(Duration::from_secs(230), async {
        stdin.write_all(&input).await.map_err(bad)?;
        drop(stdin);
        let mut output = Vec::new();
        stdout.read_to_end(&mut output).await.map_err(bad)?;
        let status = child.wait().await.map_err(bad)?;
        if output.len() > 16 * 1024 * 1024 { return Err(bad("AI 响应过大")); }
        let value: Value = serde_json::from_slice(&output).map_err(|_| bad("AI 连接进程返回无效结果"))?;
        if !status.success() { return Err(bad(value["error"].as_str().unwrap_or("AI 生成失败"))); }
        Ok(Json(value))
    }).await;
    match result {
        Ok(result) => result,
        Err(_) => { let _ = child.kill().await; Err(bad("AI 请求超时，请检查连接后重试")) }
    }
}
