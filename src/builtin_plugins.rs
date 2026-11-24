//! Release-only, one-time installation of bundled source packages; never executes them.
use std::collections::BTreeSet;
use std::path::Path;
include!(concat!(env!("OUT_DIR"), "/builtin_packages.rs"));

pub async fn install_once(root: &Path) -> Result<(), String> {
    let marker = root.join("builtin-plugins.initialized.json");
    if PACKAGES.is_empty() {
        return Ok(());
    }
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let mut initialized: BTreeSet<String> = match std::fs::read(&marker) {
        Ok(bytes) => serde_json::from_slice::<serde_json::Value>(&bytes)
            .ok()
            .and_then(|value| serde_json::from_value(value["plugins"].clone()).ok())
            .ok_or("内置插件记录格式无效")?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => BTreeSet::new(),
        Err(error) => return Err(error.to_string()),
    };
    let mut changed = false;
    for (id, bytes) in PACKAGES {
        if !initialized.insert((*id).into()) {
            continue;
        }
        changed = true;
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
    if !changed {
        return Ok(());
    }
    let data = serde_json::to_vec_pretty(&serde_json::json!({"schema":1,"plugins":initialized}))
        .map_err(|e| e.to_string())?;
    let temporary = root.join("builtin-plugins.initialized.tmp");
    std::fs::write(&temporary, data).map_err(|e| e.to_string())?;
    std::fs::rename(temporary, marker).map_err(|e| e.to_string())?;
    Ok(())
}
