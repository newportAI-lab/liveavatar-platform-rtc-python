from dataclasses import dataclass

import numpy as np


@dataclass
class AudioFrame:
    """PCM audio frame, resampled by SDK to configured sample_rate (default 16kHz mono int16)."""

    data: np.ndarray  # PCM int16 samples, shape (samples,)
    sample_rate: int  # Hz
    num_channels: int  # 1 = mono
    timestamp: int = 0  # LiveKit timestamp (microseconds)

    @classmethod
    def from_pcm(
        cls, pcm: bytes, sample_rate: int, num_channels: int = 1
    ) -> "AudioFrame":
        data = np.frombuffer(pcm, dtype=np.int16)
        return cls(data=data, sample_rate=sample_rate, num_channels=num_channels)

    @classmethod
    def from_ndarray(
        cls, data: np.ndarray, sample_rate: int, timestamp: int = 0
    ) -> "AudioFrame":
        if data.dtype != np.int16:
            data = np.clip(data, -1.0, 1.0)
            data = (data * 32767.0).round().astype(np.int16)
        return cls(
            data=data,
            sample_rate=sample_rate,
            num_channels=1 if data.ndim == 1 else data.shape[1],
            timestamp=timestamp,
        )

    def to_pcm_bytes(self) -> bytes:
        return self.data.tobytes()


@dataclass
class AudioTrackInfo:
    """Metadata for a subscribed audio track."""

    sample_rate: int
    num_channels: int
    participant_identity: str
    track_sid: str = ""


@dataclass
class TTSConfig:
    """Platform TTS parameters."""

    speed: float | None = None  # e.g. 1.0
    volume: float | None = None  # e.g. 1.0
    mood: str | None = None  # e.g. "cheerful"
