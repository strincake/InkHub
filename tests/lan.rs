use note4_screen_scheduler::lan::*;
use std::io::Write;

fn opus_frames() -> Vec<Vec<u8>> {
    let mut enc =
        opus::Encoder::new(16000, opus::Channels::Mono, opus::Application::Audio).unwrap();
    (0..2)
        .map(|_| enc.encode_vec(&[0; 960], 1180).unwrap())
        .collect()
}
#[test]
fn audio_reorders_deduplicates_and_preserves_tail() {
    let frames = opus_frames();
    let mut audio = IncomingAudio::new(9, 50, 1, 0);
    audio.chunk(1, &frames[1]);
    audio.chunk(0, &frames[0]);
    audio.chunk(0, &frames[0]);
    assert_eq!(audio.finish(2, 123).unwrap().samples.len(), 1083);
}
#[test]
fn audio_rejects_missing_conflicting_malformed_and_oversized_data() {
    let frames = opus_frames();
    let mut audio = IncomingAudio::new(9, 50, 1, 0);
    audio.chunk(1, &frames[1]);
    assert!(audio.finish(2, 960).is_err());
    for (seq, data) in [(0, vec![0; 1181]), (50, frames[0].clone()), (0, vec![])] {
        let mut audio = IncomingAudio::new(9, 50, 1, 0);
        audio.chunk(seq, &data);
        assert!(audio.finish(1, 960).is_err());
    }
    let mut audio = IncomingAudio::new(9, 50, 1, 0);
    audio.chunk(0, &frames[0]);
    audio.chunk(0, &[0]);
    assert!(audio.finish(1, 960).is_err());
    for (total, tail) in [(0, 0), (51, 960), (1, 0), (1, 961)] {
        let mut audio = IncomingAudio::new(9, 50, 1, 0);
        audio.chunk(0, &frames[0]);
        assert!(audio.finish(total, tail).is_err());
    }
}

#[test]
fn reassembles_many_chunks_out_of_order() {
    let mut seed = 19u32;
    let raw: Vec<u8> = (0..15000)
        .map(|_| {
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            seed as u8
        })
        .collect();
    let data = compressed(&raw);
    assert!(data.len() > 1024);
    let mut img = IncomingImage::new(9, 1, data.len()).unwrap();
    let chunks: Vec<_> = data.chunks(1024).collect();
    for n in (0..chunks.len()).rev() {
        img.chunk(n as u32, chunks[n]).unwrap();
    }
    assert!(img.complete());
    let pixels = img.decode(&uniform_palette()).unwrap();
    for n in 0..120000 {
        assert_eq!(
            pixels[n],
            if raw[n / 8] & (1 << (7 - n % 8)) == 0 {
                255
            } else {
                0
            }
        );
    }
}
fn compressed(raw: &[u8]) -> Vec<u8> {
    let mut z = flate2::write::ZlibEncoder::new(vec![], flate2::Compression::default());
    z.write_all(raw).unwrap();
    z.finish().unwrap()
}
#[test]
fn packet_limits() {
    assert!(Packet::decode(&[0; 15]).is_none());
    assert!(Packet::decode(&[0; 1201]).is_none());
    let p = Packet {
        kind: 5,
        connection: 77,
        sequence: 3,
        body: vec![1, 0, 8],
    };
    assert_eq!(Packet::decode(&p.encode()).unwrap().body, p.body);
}
#[test]
fn assembly_is_bounded_and_duplicate_safe() {
    let data = compressed(&vec![0; 15000]);
    let mut img = IncomingImage::new(2, 1, data.len()).unwrap();
    img.chunk(0, &data).unwrap();
    img.chunk(0, &data).unwrap();
    assert_eq!(img.decode(&uniform_palette()).unwrap().len(), 400 * 300);
    assert!(img.chunk(0, &vec![1; data.len()]).is_err());
    assert!(IncomingImage::new(1, 1, 65536).is_err());
    assert!(IncomingImage::new(1, 3, 10).is_err());
}
#[test]
fn rejects_trailing_truncated_and_wrong_length() {
    let mut data = compressed(&vec![0; 15000]);
    data.push(0);
    let mut img = IncomingImage::new(2, 1, data.len()).unwrap();
    img.chunk(0, &data).unwrap();
    assert!(img.decode(&uniform_palette()).is_err());
    let data = compressed(&[0; 1]);
    let mut img = IncomingImage::new(2, 1, data.len()).unwrap();
    img.chunk(0, &data).unwrap();
    assert!(img.decode(&uniform_palette()).is_err());
}
#[test]
fn mono_polarity() {
    let data = compressed(&vec![0; 15000]);
    let mut img = IncomingImage::new(2, 1, data.len()).unwrap();
    img.chunk(0, &data).unwrap();
    assert!(img
        .decode(&uniform_palette())
        .unwrap()
        .iter()
        .all(|v| *v == 255));
}
