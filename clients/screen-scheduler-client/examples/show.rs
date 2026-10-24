use screen_scheduler_client::{Device, ImageFormat, OpenOptions};
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let target = args.get(1).cloned().unwrap_or("127.0.0.1:38477".into());
    let path = args.get(2).ok_or("usage: show [target] picture.png")?;
    let device = Device::open(OpenOptions {
        target: Some(target),
        client_name: Some("HTTP SDK 示例".into()),
    })
    .await?;
    let png = std::fs::read(path)?;
    let receipt = device.submit(&png, ImageFormat::Gray16).await?;
    println!(
        "accepted {} revision {}",
        receipt.sequence, receipt.revision
    );
    // Keep the source alive so the scheduler can display it and return keys.
    tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    println!("result {:?}", device.receipt(receipt.sequence).await?);
    device.close().await?;
    Ok(())
}
