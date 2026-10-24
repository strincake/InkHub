//! Release-only, one-time installation of bundled source packages; never executes them.
use std::path::Path;
include!(concat!(env!("OUT_DIR"), "/builtin_packages.rs"));

pub async fn install_once(root: &Path) -> Result<(), String> {
    let marker = root.join("builtin-plugins.initialized.json");
    if PACKAGES.is_empty() || marker.exists() {
        return Ok(());
    }
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    for (id, bytes) in PACKAGES {
        if root.join("packages").join(id).exists() {
            continue;
        }
        let raw = crate::plugins::python(
            vec![
                crate::runtime::layout()
                    .script("plugin_tools.py")
                    .to_string_lossy()
                    .into(),
                "install".into(),
                root.to_string_lossy().into(),
            ],
            bytes.to_vec(),
            65536,
            10,
        )
        .await?;
        let manifest: serde_json::Value =
            serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
        if manifest["id"].as_str() != Some(id) {
            return Err(format!("内置插件标识不匹配：{id}"));
        }
    }
    let ids: Vec<_> = PACKAGES.iter().map(|(id, _)| *id).collect();
    let data = serde_json::to_vec_pretty(&serde_json::json!({"schema":1,"plugins":ids}))
        .map_err(|e| e.to_string())?;
    let temporary = root.join("builtin-plugins.initialized.tmp");
    std::fs::write(&temporary, data).map_err(|e| e.to_string())?;
    std::fs::rename(temporary, marker).map_err(|e| e.to_string())?;
    Ok(())
}
