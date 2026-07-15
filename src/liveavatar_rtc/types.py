from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .errors import AudioFormatError


@dataclass(frozen=True)
class FrontendConnection:
    user_token: str
    sfu_url: str


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    agent_token: str
    user_token: str
    sfu_url: str
    output_sample_rate: int | None = None


@dataclass(frozen=True)
class DataChannelEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    response_id: str | None = None
    seq: int | None = None
    timestamp: int | None = None
    participant_identity: str | None = None
    topic: str | None = None


@dataclass
class AudioFrame:
    """A mono PCM16 frame. The SDK does not resample; input and output rates are configured independently."""

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

    def validate_for_output(self, output_sample_rate: int) -> None:
        if self.data.dtype != np.int16:
            raise AudioFormatError("output audio must use int16 PCM samples")
        if self.num_channels != 1 or self.data.ndim != 1:
            raise AudioFormatError("output audio must be mono")
        if self.sample_rate != output_sample_rate:
            raise AudioFormatError(
                f"output sample rate must be {output_sample_rate}, got {self.sample_rate}"
            )


@dataclass
class AudioTrackInfo:
    """Metadata for a subscribed audio track."""

    sample_rate: int
    num_channels: int
    participant_identity: str
    track_sid: str = ""
