//! Unmodified vendor SDK types and transport; only the destination points at the gateway.
use zectrix_core::{Device, Event, ImageFormat, OpenOptions};
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let device = Device::open(OpenOptions {
        target: Some(args[1].clone()),
        client_name: Some("原版 SDK 测试".into()),
    })
    .await?;
    device
        .show_with_format(&std::fs::read(&args[2])?, ImageFormat::Gray16)
        .await?;
    println!("accepted by virtual gateway");
    let event =
        tokio::time::timeout(std::time::Duration::from_secs(12), device.next_event()).await??;
    if let Some(Event::Key { key, .. }) = event {
        println!("key {key:?}");
    } else {
        return Err("expected key".into());
    }
    device.close().await?;
    Ok(())
}
