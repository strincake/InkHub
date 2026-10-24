"""Short PCM chimes synthesized locally; ZECTRIX MIT source attribution in LICENSE."""
import io
import math
import struct
import wave


def wav_bytes(status):
    if status not in ('waiting', 'done'):
        raise ValueError('仅支持等待和完成提示音')
    notes = ((660, 180), (0, 110), (660, 260)) if status == 'waiting' else (
        (523.25, 130), (659.25, 130), (783.99, 300))
    pcm = bytearray()
    for frequency, ms in notes:
        count = ms * 16
        for i in range(count):
            envelope = min(i/160, 1) * min((count-i)/480, 1)
            phase = math.tau * frequency * i / 16000
            sample = int((math.sin(phase) + .15*math.sin(2*phase)) * envelope * 14000)
            pcm.extend(struct.pack('<h', sample))
    output = io.BytesIO()
    with wave.open(output, 'wb') as clip:
        clip.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        clip.writeframes(pcm)
    return output.getvalue()
