import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from liveavatar_rtc.types import AudioFrame


# ── Fixture ──────────────────────────────────────────────────


@pytest.fixture
def lk():
    """Create a LiveKitManager with mocked livekit.rtc dependencies."""
    mock_room = MagicMock()
    mock_room.connect = AsyncMock()
    mock_room.disconnect = AsyncMock()
    mock_room.local_participant = MagicMock()
    mock_room.local_participant.publish_track = AsyncMock()
    mock_room.local_participant.publish_data = AsyncMock()

    mock_audio_source = MagicMock()
    mock_audio_source.aclose = AsyncMock()
    mock_audio_source.capture_frame = AsyncMock()

    mock_audio_track = MagicMock()

    # Writable PCM buffer for publish_audio_frame tests
    pcm_buffer = np.zeros(480, dtype=np.int16)
    mock_lk_frame = MagicMock()
    mock_lk_frame.data = memoryview(bytearray(pcm_buffer.tobytes()))
    mock_lk_frame.sample_rate = 24000
    mock_lk_frame.num_channels = 1

    with (
        patch("livekit.rtc.Room", return_value=mock_room),
        patch("livekit.rtc.AudioSource", return_value=mock_audio_source),
        patch(
            "livekit.rtc.LocalAudioTrack.create_audio_track",
            return_value=mock_audio_track,
        ),
        patch("livekit.rtc.AudioStream") as mock_audio_stream_cls,
        patch(
            "livekit.rtc.AudioFrame.create", return_value=mock_lk_frame
        ) as mock_af_create,
    ):
        from liveavatar_rtc.livekit_manager import LiveKitManager

        manager = LiveKitManager(
            session_id="test-session",
            sfu_url="wss://sfu.test.com",
            agent_token="test-token",
            sample_rate=16000,
        )
        manager._room = mock_room
        manager._audio_source = mock_audio_source
        manager._audio_track = mock_audio_track

        yield manager, mock_room, mock_audio_source, mock_audio_track, mock_audio_stream_cls, mock_lk_frame, mock_af_create


# Helpers to unpack fixture cleanly
def _mgr(fixture):
    return fixture[0]


def _room(fixture):
    return fixture[1]


def _src(fixture):
    return fixture[2]


def _trk(fixture):
    return fixture[3]


def _stream_cls(fixture):
    return fixture[4]


def _lk_frame(fixture):
    return fixture[5]


def _af_create(fixture):
    return fixture[6]


# ── Tests ────────────────────────────────────────────────────


class TestBasics:
    def test_identity(self, lk):
        assert _mgr(lk).identity == "agent_test-session"

    def test_session_id_property(self, lk):
        assert _mgr(lk).session_id == "test-session"

    def test_sfu_url_property(self, lk):
        assert _mgr(lk).sfu_url == "wss://sfu.test.com"

    def test_user_token_property(self, lk):
        assert _mgr(lk).user_token == ""

    def test_room_property(self, lk):
        assert _mgr(lk).room is _room(lk)

    def test_init_default_sample_rate(self):
        with (
            patch("livekit.rtc.Room"),
            patch("livekit.rtc.AudioSource"),
            patch("livekit.rtc.LocalAudioTrack.create_audio_track"),
        ):
            from liveavatar_rtc.livekit_manager import LiveKitManager

            manager = LiveKitManager(
                session_id="sess", sfu_url="wss://sfu", agent_token="tok"
            )
            assert manager._sample_rate == 16000


class TestConnect:
    @pytest.mark.asyncio
    async def test_connects_and_publishes_track(self, lk):
        mgr = _mgr(lk)
        await mgr.connect()
        _room(lk).connect.assert_called_once_with("wss://sfu.test.com", "test-token")
        _room(lk).local_participant.publish_track.assert_called_once_with(_trk(lk))

    @pytest.mark.asyncio
    async def test_wait_until_ready_timeout(self, lk):
        with pytest.raises(asyncio.TimeoutError):
            await _mgr(lk).wait_until_ready(timeout=0.01)


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnects_and_cleans_up(self, lk):
        mgr = _mgr(lk)

        async def fake_consumer():
            await asyncio.sleep(10)

        task = asyncio.create_task(fake_consumer())
        mgr._audio_streams["track_sid_1"] = MagicMock()
        mgr._stream_tasks["track_sid_1"] = task

        await mgr.disconnect()

        assert len(mgr._audio_streams) == 0
        assert len(mgr._stream_tasks) == 0
        _src(lk).aclose.assert_called_once()
        _room(lk).disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_without_audio_source(self, lk):
        mgr = _mgr(lk)
        mgr._audio_source = None
        await mgr.disconnect()
        _room(lk).disconnect.assert_called_once()


class TestPublishAudio:
    @pytest.mark.asyncio
    async def test_publishes_frame_to_source(self, lk):
        mgr = _mgr(lk)
        frame = AudioFrame(
            data=np.array([0, 1, 2], dtype=np.int16),
            sample_rate=16000,
            num_channels=1,
        )
        await mgr.publish_audio_frame(frame)
        _src(lk).capture_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_audio_source_is_none(self, lk):
        mgr = _mgr(lk)
        mgr._audio_source = None
        frame = AudioFrame(
            data=np.array([0], dtype=np.int16), sample_rate=16000, num_channels=1
        )
        await mgr.publish_audio_frame(frame)  # Should not raise


class TestSendData:
    @pytest.mark.asyncio
    async def test_sends_json_to_data_channel(self, lk):
        await _mgr(lk).send_data("test.event", {"key": "value"})
        call_args = _room(lk).local_participant.publish_data.call_args
        payload = json.loads(call_args[0][0])
        assert payload["event"] == "test.event"
        assert payload["data"] == {"key": "value"}
        assert call_args.kwargs.get("reliable") is True
        assert call_args.kwargs.get("topic") == "liveavatar"

    @pytest.mark.asyncio
    async def test_sends_data_with_none_payload(self, lk):
        await _mgr(lk).send_data("simple.event")
        payload = json.loads(_room(lk).local_participant.publish_data.call_args[0][0])
        assert payload["data"] == {}


class TestRoomEvents:
    @pytest.mark.asyncio
    async def test_on_disconnected_dispatches_event(self, lk):
        mgr = _mgr(lk)
        received = []

        @mgr.events.on("disconnected")
        async def handler(reason):
            received.append(reason)

        reason = MagicMock()
        reason.__str__ = MagicMock(return_value="DisconnectReason.USER_LEFT")
        await mgr._on_disconnected(reason)
        assert received == ["DisconnectReason.USER_LEFT"]

    @pytest.mark.asyncio
    async def test_on_participant_connected_user(self, lk):
        mgr = _mgr(lk)
        received = []

        @mgr.events.on("user_joined")
        async def handler(identity):
            received.append(identity)

        participant = MagicMock()
        participant.identity = "user_alice123"
        await mgr._on_participant_connected(participant)
        assert received == ["user_alice123"]
        assert mgr._ready_event.is_set()

    def test_on_participant_connected_non_user(self, lk):
        mgr = _mgr(lk)
        participant = MagicMock()
        participant.identity = "agent_other"
        asyncio.run(mgr._on_participant_connected(participant))
        assert not mgr._ready_event.is_set()

    def test_on_reconnecting(self, lk):
        asyncio.run(_mgr(lk)._on_reconnecting())


class TestTrackEvents:
    @pytest.mark.asyncio
    async def test_on_track_subscribed_remote_audio(self, lk):
        mgr = _mgr(lk)
        events = []

        @mgr.events.on("user_audio_track_subscribed")
        async def handler(info):
            events.append(info)

        track = MagicMock(spec=["sid"])
        track.sid = "TR_test123"
        publication = MagicMock()
        participant = MagicMock()
        participant.identity = "user_alice"

        mock_stream = AsyncMock()
        mock_stream.__aiter__.return_value = []
        _stream_cls(lk).return_value = mock_stream

        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            await mgr._on_track_subscribed(track, publication, participant)

        assert len(events) == 1
        info = events[0]
        assert info.participant_identity == "user_alice"
        assert info.sample_rate == 16000
        assert info.num_channels == 1
        assert info.track_sid == "TR_test123"
        assert "TR_test123" in mgr._audio_streams
        assert "TR_test123" in mgr._stream_tasks

    @pytest.mark.asyncio
    async def test_on_track_subscribed_non_audio_skipped(self, lk):
        mgr = _mgr(lk)
        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=False):
            await mgr._on_track_subscribed(MagicMock(), MagicMock(), MagicMock())
        assert len(mgr._audio_streams) == 0

    @pytest.mark.asyncio
    async def test_on_track_subscribed_non_user_skipped(self, lk):
        mgr = _mgr(lk)
        participant = MagicMock()
        participant.identity = "agent_other"
        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            await mgr._on_track_subscribed(MagicMock(), MagicMock(), participant)
        assert len(mgr._audio_streams) == 0

    @pytest.mark.asyncio
    async def test_on_track_unsubscribed_cleans_up(self, lk):
        mgr = _mgr(lk)
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancel = MagicMock()
        mgr._audio_streams["TR_cleanup"] = MagicMock()
        mgr._stream_tasks["TR_cleanup"] = mock_task

        track = MagicMock()
        track.sid = "TR_cleanup"
        await mgr._on_track_unsubscribed(track, MagicMock(), MagicMock())

        mock_task.cancel.assert_called_once()
        assert "TR_cleanup" not in mgr._audio_streams
        assert "TR_cleanup" not in mgr._stream_tasks

    @pytest.mark.asyncio
    async def test_on_track_unsubscribed_unknown_track_noop(self, lk):
        track = MagicMock()
        track.sid = "TR_unknown"
        await _mgr(lk)._on_track_unsubscribed(track, MagicMock(), MagicMock())


class TestDataChannel:
    @pytest.mark.asyncio
    async def test_on_data_received_valid_json(self, lk):
        mgr = _mgr(lk)
        events = []

        @mgr.events.on("test.event")
        async def handler(data):
            events.append(data)

        packet = MagicMock()
        packet.data = json.dumps({"event": "test.event", "data": {"key": "val"}})
        await mgr._on_data_received(packet)
        assert events == [{"key": "val"}]

    @pytest.mark.asyncio
    async def test_on_data_received_without_data_field(self, lk):
        mgr = _mgr(lk)
        events = []

        @mgr.events.on("test.event")
        async def handler(data):
            events.append(data)

        packet = MagicMock()
        packet.data = json.dumps({"event": "test.event"})
        await mgr._on_data_received(packet)
        assert events == [{}]

    @pytest.mark.asyncio
    async def test_on_data_received_invalid_json(self, lk):
        packet = MagicMock()
        packet.data = "not valid json{{{"
        await _mgr(lk)._on_data_received(packet)  # Should not raise


class TestConsumeAudio:
    @pytest.mark.asyncio
    async def test_dispatches_frames(self, lk):
        mgr = _mgr(lk)
        frames = []

        @mgr.events.on("user_audio_frame")
        async def handler(frame):
            frames.append(frame)

        pcm = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        lkf = MagicMock()
        lkf.data = memoryview(pcm.tobytes())
        lkf.sample_rate = 16000
        lkf.num_channels = 1
        lkf.timestamp_us = 100

        fe = MagicMock()
        fe.frame = lkf

        stream = AsyncMock()
        stream.__aiter__.return_value = [fe]

        await mgr._consume_audio_stream("TR_test", stream)

        assert len(frames) == 1
        f = frames[0]
        assert f.sample_rate == 16000
        assert f.num_channels == 1
        assert f.timestamp == 100
        np.testing.assert_array_equal(f.data, pcm)

    @pytest.mark.asyncio
    async def test_non_memoryview_data(self, lk):
        mgr = _mgr(lk)
        frames = []

        @mgr.events.on("user_audio_frame")
        async def handler(frame):
            frames.append(frame)

        pcm = np.array([10, 20, 30], dtype=np.int16)
        lkf = MagicMock()
        lkf.data = pcm
        lkf.sample_rate = 24000
        lkf.num_channels = 2
        lkf.timestamp_us = 200

        fe = MagicMock()
        fe.frame = lkf

        stream = AsyncMock()
        stream.__aiter__.return_value = [fe]

        await mgr._consume_audio_stream("TR_test", stream)

        assert len(frames) == 1
        assert frames[0].sample_rate == 24000
        assert frames[0].num_channels == 2

    @pytest.mark.asyncio
    async def test_cancelled_silently(self, lk):
        mgr = _mgr(lk)
        stream = AsyncMock()
        stream.__aiter__.side_effect = asyncio.CancelledError()
        await mgr._consume_audio_stream("TR_test", stream)

    @pytest.mark.asyncio
    async def test_error_logged(self, lk, caplog):
        stream = AsyncMock()
        stream.__aiter__.side_effect = RuntimeError("stream broken")
        await _mgr(lk)._consume_audio_stream("TR_bad", stream)
        assert "Error consuming audio stream TR_bad" in caplog.text
