import numpy as np
import pytest

from liveavatar_rtc.types import AudioFrame, AudioTrackInfo, TTSConfig


class TestAudioFrame:
    def test_from_pcm_basic(self):
        # 3 samples, little-endian int16: 0, 256, 512
        pcm = b"\x00\x00\x00\x01\x00\x02"
        frame = AudioFrame.from_pcm(pcm, sample_rate=16000, num_channels=1)
        assert frame.sample_rate == 16000
        assert frame.num_channels == 1
        assert len(frame.data) == 3
        assert frame.data.dtype == np.int16
        assert frame.data[0] == 0
        assert frame.data[1] == 256
        assert frame.data[2] == 512

    def test_from_pcm_stereo(self):
        pcm = b"\x00\x00\x01\x00\x02\x00\x03\x00"  # 4 samples
        frame = AudioFrame.from_pcm(pcm, sample_rate=44100, num_channels=2)
        assert frame.sample_rate == 44100
        assert frame.num_channels == 2
        assert len(frame.data) == 4

    def test_from_pcm_default_channels(self):
        pcm = b"\x00\x00\x01\x00"
        frame = AudioFrame.from_pcm(pcm, sample_rate=8000)
        assert frame.num_channels == 1

    def test_from_ndarray_int16(self):
        data = np.array([0, 100, 200, 300], dtype=np.int16)
        frame = AudioFrame.from_ndarray(data, sample_rate=16000, timestamp=42)
        assert frame.sample_rate == 16000
        assert frame.num_channels == 1
        assert frame.timestamp == 42
        np.testing.assert_array_equal(frame.data, data)

    def test_from_ndarray_float_converts_to_int16(self):
        data = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
        frame = AudioFrame.from_ndarray(data, sample_rate=16000)
        assert frame.data.dtype == np.int16
        expected = np.array([0, 16384, -16384, 32767], dtype=np.int16)
        np.testing.assert_array_equal(frame.data, expected)

    def test_from_ndarray_stereo_float(self):
        data = np.array([[0.0, 0.5], [-0.5, 1.0]], dtype=np.float32)
        frame = AudioFrame.from_ndarray(data, sample_rate=24000)
        assert frame.num_channels == 2
        assert frame.data.shape == (2, 2)

    def test_to_pcm_bytes(self):
        data = np.array([0, 1, -1, 32767, -32768], dtype=np.int16)
        frame = AudioFrame(data=data, sample_rate=16000, num_channels=1)
        pcm = frame.to_pcm_bytes()
        reconstructed = np.frombuffer(pcm, dtype=np.int16)
        np.testing.assert_array_equal(reconstructed, data)

    def test_to_pcm_bytes_empty(self):
        frame = AudioFrame(data=np.array([], dtype=np.int16), sample_rate=16000, num_channels=1)
        assert frame.to_pcm_bytes() == b""

    def test_default_timestamp(self):
        frame = AudioFrame(data=np.array([0], dtype=np.int16), sample_rate=16000, num_channels=1)
        assert frame.timestamp == 0


class TestAudioTrackInfo:
    def test_basic_fields(self):
        info = AudioTrackInfo(
            sample_rate=16000,
            num_channels=1,
            participant_identity="user_alice",
            track_sid="TR_abc123",
        )
        assert info.sample_rate == 16000
        assert info.num_channels == 1
        assert info.participant_identity == "user_alice"
        assert info.track_sid == "TR_abc123"

    def test_default_track_sid(self):
        info = AudioTrackInfo(
            sample_rate=24000,
            num_channels=2,
            participant_identity="user_bob",
        )
        assert info.track_sid == ""


class TestTTSConfig:
    def test_defaults(self):
        cfg = TTSConfig()
        assert cfg.speed is None
        assert cfg.volume is None
        assert cfg.mood is None

    def test_with_values(self):
        cfg = TTSConfig(speed=1.5, volume=0.8, mood="cheerful")
        assert cfg.speed == 1.5
        assert cfg.volume == 0.8
        assert cfg.mood == "cheerful"

    def test_partial(self):
        cfg = TTSConfig(speed=1.2)
        assert cfg.speed == 1.2
        assert cfg.volume is None
        assert cfg.mood is None
