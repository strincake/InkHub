//! Bounded subset of the vendor LAN v1 wire format. No audio emulation.
use std::io::Read;
#[derive(Clone, Debug)]
pub struct Packet {
    pub kind: u8,
    pub connection: u64,
    pub sequence: u32,
    pub body: Vec<u8>,
}
impl Packet {
    pub fn decode(b: &[u8]) -> Option<Self> {
        if !(16..=1200).contains(&b.len()) || b[..3] != [b'Z', b'L', 1] {
            return None;
        }
        Some(Self {
            kind: b[3],
            connection: u64::from_be_bytes(b[4..12].try_into().ok()?),
            sequence: u32::from_be_bytes(b[12..16].try_into().ok()?),
            body: b[16..].to_vec(),
        })
    }
    pub fn encode(&self) -> Vec<u8> {
        let mut b = vec![b'Z', b'L', 1, self.kind];
        b.extend(self.connection.to_be_bytes());
        b.extend(self.sequence.to_be_bytes());
        b.extend(&self.body);
        b
    }
    pub fn reply(&self, body: Vec<u8>) -> Self {
        Self {
            kind: self.kind | 128,
            connection: self.connection,
            sequence: self.sequence,
            body,
        }
    }
}
pub fn uniform_palette() -> [u8; 20] {
    let mut p = [0; 20];
    p[..4].copy_from_slice(&[0, 85, 170, 255]);
    for n in 0..16 {
        p[n + 4] = n as u8 * 17
    }
    p
}
pub struct IncomingImage {
    pub id: u32,
    pub bpp: u8,
    pub size: usize,
    pub bitmap: u64,
    pub state: u8,
    chunks: Vec<Option<Vec<u8>>>,
}
impl IncomingImage {
    pub fn new(id: u32, bpp: u8, size: usize) -> Result<Self, String> {
        if id == 0 || ![1, 2, 4].contains(&bpp) || !(1..=65535).contains(&size) {
            return Err("invalid image header".into());
        }
        Ok(Self {
            id,
            bpp,
            size,
            bitmap: 0,
            state: 1,
            chunks: vec![None; size.div_ceil(1024)],
        })
    }
    pub fn chunk(&mut self, n: u32, data: &[u8]) -> Result<(), String> {
        let n = n as usize;
        if n >= self.chunks.len() || data.len() != (self.size - n * 1024).min(1024) {
            return Err("invalid chunk length".into());
        }
        if let Some(old) = &self.chunks[n] {
            if old != data {
                self.state = 4;
                return Err("conflicting duplicate".into());
            }
            return Ok(());
        }
        self.chunks[n] = Some(data.into());
        self.bitmap |= 1u64 << n;
        Ok(())
    }
    pub fn complete(&self) -> bool {
        self.bitmap == (u64::MAX >> (64 - self.chunks.len()))
    }
    pub fn decode(&self, palette: &[u8; 20]) -> Result<Vec<u8>, String> {
        if !self.complete() || self.state == 4 {
            return Err("incomplete image".into());
        }
        let compressed: Vec<u8> = self
            .chunks
            .iter()
            .flat_map(|c| c.as_ref().unwrap().iter().copied())
            .collect();
        let mut decoder = flate2::read::ZlibDecoder::new(compressed.as_slice());
        let expected = 15000 * self.bpp as usize;
        let mut raw = vec![];
        decoder
            .by_ref()
            .take(expected as u64 + 1)
            .read_to_end(&mut raw)
            .map_err(|e| e.to_string())?;
        if raw.len() != expected || decoder.total_in() != compressed.len() as u64 {
            return Err("invalid zlib or decoded length".into());
        }
        let mask = (1 << self.bpp) - 1;
        Ok((0..120000)
            .map(|n| {
                let code = (raw[n * self.bpp as usize / 8]
                    >> (8 - self.bpp - (n * self.bpp as usize % 8) as u8))
                    & mask;
                if self.bpp == 1 {
                    if code == 0 {
                        255
                    } else {
                        0
                    }
                } else {
                    let linear = palette[if self.bpp == 2 {
                        code as usize
                    } else {
                        4 + code as usize
                    }] as f64
                        / 255.;
                    ((if linear <= 0.0031308 {
                        12.92 * linear
                    } else {
                        1.055 * linear.powf(1. / 2.4) - 0.055
                    }) * 255.)
                        .round() as u8
                }
            })
            .collect())
    }
}
