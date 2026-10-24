//! Verify the unchanged vendor SDK's short audio through the managed UDP gateway.
use zectrix_core::{AudioClip, Device, OpenOptions};
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let device = Device::open(OpenOptions {
        target: Some(args[1].clone()),
        client_name: Some("UDP audio example".into()),
    })
    .await?;
    device.show(&std::fs::read(&args[2])?).await?;
    let clip = AudioClip {
        samples: (0..1600)
            .map(|n| ((n as f32 * 0.17).sin() * 2000.) as i16)
            .collect(),
    };
    let result = device.play(&clip, 25).await?;
    println!("managed_audio={result:?}");
    // Keep the source alive long enough for the test host to observe output.
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    device.close().await?;
    Ok(())
}
