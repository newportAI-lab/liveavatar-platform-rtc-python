import numpy as np
import pytest

from liveavatar_rtc import AudioFormatError, DataChannelEvent, FrontendConnection
from liveavatar_rtc.types import AudioFrame


def test_frontend_connection_is_immutable():
    connection = FrontendConnection(user_token="user-token", sfu_url="wss://sfu")
    with pytest.raises(AttributeError):
        connection.user_token = "changed"


def test_data_channel_event_preserves_envelope():
    event = DataChannelEvent(
        event="session.state",
        data={"state": "IDLE"},
        request_id="req-1",
        response_id="res-1",
        seq=7,
        timestamp=1234,
        participant_identity="coordinator_s1",
        topic="liveavatar",
    )
    assert event.seq == 7
    assert event.participant_identity == "coordinator_s1"


def test_audio_frame_rejects_non_pcm16():
    frame = AudioFrame.from_ndarray(np.array([0.1], dtype=np.float32), 24000)
    assert frame.data.dtype == np.int16
    bad = AudioFrame(np.array([1], dtype=np.int32), 24000, 1)
    with pytest.raises(AudioFormatError, match="int16"):
        bad.validate_for_output(24000)


def test_audio_frame_docstring_describes_format_and_rate_handling():
    doc = AudioFrame.__doc__ or ""
    assert "mono PCM" in doc
    assert "does not resample" in doc
    assert "independently" in doc
