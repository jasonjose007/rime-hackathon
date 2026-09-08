import struct
import io


def pcm_to_wav_header(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data


def ensure_wav_header(audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF":
        return audio_bytes
    return pcm_to_wav_header(audio_bytes, sample_rate=sample_rate)


def chunk_audio(audio_data: bytes, chunk_size: int = 4096) -> list[bytes]:
    chunks = []
    for i in range(0, len(audio_data), chunk_size):
        chunks.append(audio_data[i:i + chunk_size])
    return chunks


def compute_rms(pcm_data: bytes) -> float:
    if len(pcm_data) < 2:
        return 0.0
    num_samples = len(pcm_data) // 2
    total = 0.0
    for i in range(num_samples):
        sample = struct.unpack_from("<h", pcm_data, i * 2)[0]
        total += sample * sample
    return (total / num_samples) ** 0.5


def is_silence(pcm_data: bytes, threshold: float = 500.0) -> bool:
    return compute_rms(pcm_data) < threshold


def resample_linear(pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
    if from_rate == to_rate:
        return pcm_data

    num_samples = len(pcm_data) // 2
    samples = [struct.unpack_from("<h", pcm_data, i * 2)[0] for i in range(num_samples)]

    ratio = from_rate / to_rate
    new_length = int(num_samples / ratio)
    resampled = []

    for i in range(new_length):
        src_idx = i * ratio
        idx = int(src_idx)
        frac = src_idx - idx

        if idx + 1 < num_samples:
            val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
        else:
            val = samples[idx] if idx < num_samples else 0

        resampled.append(max(-32768, min(32767, int(val))))

    return struct.pack(f"<{len(resampled)}h", *resampled)
