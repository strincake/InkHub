//! Legacy settings compatibility only; no runtime image-pool implementation.
use super::*;
pub async fn legacy_gallery(config: &std::path::Path) -> Result<(), String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let raw = plugins::python(
        vec![
            root.join("python/migrate_gallery.py").to_string_lossy().into(),
            config.to_string_lossy().into(),
            root.join("plugins/local-gallery")
                .to_string_lossy()
                .into(),
        ],
        vec![],
        65536,
        15,
    )
    .await?;
    let result: Value = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    if result["migrated"].as_u64().unwrap_or(0) > 0
        || result["consolidated"].as_u64().unwrap_or(0) > 0
    {
        eprintln!("已迁移并合并本地相册；原配置、插件包与数据已保留备份");
    }
    Ok(())
}
