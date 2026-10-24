use screen_scheduler_client as zectrix_sdk;
use zectrix_sdk::{Device, Event, ImageFormat, OpenOptions};
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let device = Device::open(OpenOptions {
        target: Some(args[1].clone()),
        client_name: Some("Rust HTTP 回环".into()),
    })
    .await?;
    let r = device
        .submit(&std::fs::read(&args[2])?, ImageFormat::Gray4)
        .await?;
    assert!(matches!(
        device.receipt(0).await,
        Err(zectrix_sdk::Error::ResultUnknown)
    ));
    println!("accepted {}", r.sequence);
    let e = tokio::time::timeout(std::time::Duration::from_secs(12), device.next_event()).await??;
    if let Some(Event::Key { key, .. }) = e {
        println!("key {key:?}");
    } else {
        return Err("expected key".into());
    }
    println!("receipt {}", device.receipt(r.sequence).await?.state);
    device.close().await?;
    Ok(())
}
