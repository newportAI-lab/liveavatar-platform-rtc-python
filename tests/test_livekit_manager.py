import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from livekit import rtc
from livekit.rtc.event_emitter import EventEmitter

from liveavatar_rtc.errors import (
    AudioFormatError,
    DataChannelProtocolError,
    RTCConnectionError,
)
from liveavatar_rtc.session import Session
from liveavatar_rtc.types import AudioFrame, AudioTrackInfo, DataChannelEvent


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
    mock_audio_source.clear_queue = MagicMock()

    mock_audio_track = MagicMock()

    # Writable PCM buffer for publish_audio_frame tests
    pcm_buffer = np.zeros(3, dtype=np.int16)
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
            input_sample_rate=16000,
            output_sample_rate=24000,
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
    @pytest.mark.asyncio
    async def test_room_events_register_sync_callbacks_that_schedule_handlers(self):
        room = EventEmitter()
        with patch("livekit.rtc.Room", return_value=room):
            from liveavatar_rtc.livekit_manager import LiveKitManager

            with pytest.warns(DeprecationWarning):
                manager = LiveKitManager("test-session", "wss://sfu", "token")

        handler = AsyncMock()
        manager.events.add("renderer_joined", handler)
        room.emit(
            "participant_connected",
            MagicMock(identity="renderer_test-session"),
        )
        await asyncio.sleep(0)

        handler.assert_awaited_once_with("renderer_test-session")

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
            assert manager._input_sample_rate == 16000
            assert manager._output_sample_rate == 24000


class TestConnect:
    @pytest.mark.asyncio
    async def test_connects_and_publishes_track(self, lk):
        mgr = _mgr(lk)
        await mgr.connect()
        _room(lk).connect.assert_called_once_with("wss://sfu.test.com", "test-token")
        _room(lk).local_participant.publish_track.assert_called_once_with(_trk(lk))
        rtc.AudioSource.assert_called_once_with(
            sample_rate=24000, num_channels=1, queue_size_ms=200
        )

    @pytest.mark.asyncio
    async def test_wait_until_ready_timeout(self, lk):
        with pytest.raises(asyncio.TimeoutError):
            await _mgr(lk).wait_until_ready(timeout=0.01)


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self, lk):
        mgr = _mgr(lk)

        await asyncio.gather(mgr.disconnect(), mgr.disconnect())

        _src(lk).aclose.assert_awaited_once_with()
        _room(lk).disconnect.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_disconnect_preserves_source_error_and_still_disconnects_room(
        self, lk
    ):
        mgr = _mgr(lk)
        _src(lk).aclose.side_effect = RuntimeError("source close failed")

        with pytest.raises(RuntimeError, match="source close failed"):
            await mgr.disconnect()

        _room(lk).disconnect.assert_awaited_once_with()

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
    async def test_disconnect_closes_user_audio_stream(self, lk):
        mgr = _mgr(lk)
        stream = AsyncMock()
        mgr._user_audio_stream = stream

        await mgr.disconnect()

        stream.aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_disconnect_guard_blocks_queued_track_subscription(self, lk):
        mgr = _mgr(lk)
        close_started = asyncio.Event()
        release_close = asyncio.Event()
        old_stream = AsyncMock()

        async def block_close():
            close_started.set()
            await release_close.wait()

        old_stream.aclose.side_effect = block_close
        mgr._user_audio_stream = old_stream
        _stream_cls(lk).reset_mock()
        track = MagicMock(sid="late")
        publication = MagicMock(source=rtc.TrackSource.SOURCE_MICROPHONE)
        participant = MagicMock(identity="user_alice")

        disconnect_task = asyncio.create_task(mgr.disconnect())
        await close_started.wait()
        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            subscription_task = asyncio.create_task(
                mgr._on_track_subscribed(track, publication, participant)
            )
            await asyncio.sleep(0)
            assert not subscription_task.done()
            release_close.set()
            await asyncio.gather(disconnect_task, subscription_task)

        _stream_cls(lk).assert_not_called()
        assert mgr._user_audio_stream is None
        assert mgr._user_audio_task is None
        assert mgr._user_audio_track_sid is None

    @pytest.mark.asyncio
    async def test_disconnect_cancels_tracked_room_tasks_without_self_await(self, lk):
        mgr = _mgr(lk)
        current = asyncio.current_task()
        blocked = asyncio.create_task(asyncio.Event().wait())
        mgr._room_event_tasks.update((current, blocked))

        await mgr.disconnect()

        assert blocked.cancelled()
        assert not current.cancelled()
        assert mgr._room_event_tasks == {current}

    @pytest.mark.asyncio
    async def test_disconnect_without_audio_source(self, lk):
        mgr = _mgr(lk)
        mgr._audio_source = None
        await mgr.disconnect()
        _room(lk).disconnect.assert_called_once()


class TestPublishAudio:
    @pytest.mark.asyncio
    async def test_clear_output_queue_uses_connected_audio_source(self, lk):
        await _mgr(lk).clear_output_queue()

        _src(lk).clear_queue.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_clear_output_queue_without_source_is_noop(self, lk):
        mgr = _mgr(lk)
        mgr._audio_source = None

        await mgr.clear_output_queue()

    @pytest.mark.asyncio
    async def test_publishes_frame_to_source(self, lk):
        mgr = _mgr(lk)
        frame = AudioFrame(
            data=np.array([0, 1, 2], dtype=np.int16),
            sample_rate=24000,
            num_channels=1,
        )
        await mgr.publish_audio_frame(frame)
        _src(lk).capture_frame.assert_called_once()
        _af_create(lk).assert_called_once_with(
            sample_rate=24000, num_channels=1, samples_per_channel=3
        )
        assert np.frombuffer(_lk_frame(lk).data, dtype=np.int16)[:3].tolist() == [
            0,
            1,
            2,
        ]

    @pytest.mark.asyncio
    async def test_rejects_wrong_output_rate(self, lk):
        frame = AudioFrame.from_pcm(b"\x00\x00", sample_rate=16000)

        with pytest.raises(AudioFormatError, match="24000"):
            await _mgr(lk).publish_audio_frame(frame)

        _src(lk).capture_frame.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_when_audio_source_is_none(self, lk):
        mgr = _mgr(lk)
        mgr._audio_source = None
        frame = AudioFrame(
            data=np.array([0], dtype=np.int16), sample_rate=24000, num_channels=1
        )
        with pytest.raises(RTCConnectionError, match="not connected"):
            await mgr.publish_audio_frame(frame)

    @pytest.mark.asyncio
    async def test_copies_samples_into_real_livekit_frame_buffer(self):
        source = MagicMock(capture_frame=AsyncMock())
        with patch("livekit.rtc.Room"):
            from liveavatar_rtc.livekit_manager import LiveKitManager

            manager = LiveKitManager("session", "wss://sfu", "token")
        manager._audio_source = source
        frame = AudioFrame.from_pcm(
            b"\x01\x00\xfe\xff\x03\x00", sample_rate=24000
        )

        await manager.publish_audio_frame(frame)

        captured = source.capture_frame.await_args.args[0]
        assert np.frombuffer(captured.data.cast("b"), dtype=np.int16).tolist() == [
            1,
            -2,
            3,
        ]


class TestSendData:
    @pytest.mark.asyncio
    async def test_sends_json_to_data_channel(self, lk):
        await _mgr(lk).send_data("test.event", {"key": "value"})
        call_args = _room(lk).local_participant.publish_data.call_args
        payload = json.loads(call_args[0][0])
        assert payload["event"] == "test.event"
        assert payload["data"] == {"key": "value"}
        assert call_args.kwargs == {"reliable": True}

    @pytest.mark.asyncio
    async def test_sends_data_with_none_payload(self, lk):
        await _mgr(lk).send_data("simple.event")
        payload = json.loads(_room(lk).local_participant.publish_data.call_args[0][0])
        assert payload["data"] == {}

    @pytest.mark.asyncio
    async def test_send_data_event_preserves_non_none_envelope_fields(self, lk):
        event = DataChannelEvent(
            event="session.state",
            data={"state": "IDLE"},
            request_id="r1",
            response_id=None,
            seq=0,
            timestamp=99,
            participant_identity="coordinator_test-session",
            topic="ignored",
        )

        await _mgr(lk).send_data_event(event)

        call = _room(lk).local_participant.publish_data.call_args
        assert json.loads(call.args[0]) == {
            "event": "session.state",
            "data": {"state": "IDLE"},
            "requestId": "r1",
            "seq": 0,
            "timestamp": 99,
        }
        assert call.kwargs == {"reliable": True}


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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("identity", "event"),
        [
            ("coordinator_test-session", "coordinator_joined"),
            ("renderer_test-session", "renderer_joined"),
        ],
    )
    async def test_participant_roles_are_dispatched(self, lk, identity, event):
        mgr = _mgr(lk)
        received = []
        mgr.events.add(event, AsyncMock(side_effect=received.append))
        participant = MagicMock(identity=identity)

        await mgr._on_participant_connected(participant)

        assert received == [identity]

    @pytest.mark.asyncio
    async def test_participant_disconnected_dispatches_role_event(self, lk):
        mgr = _mgr(lk)
        handler = AsyncMock()
        mgr.events.add("renderer_left", handler)

        await mgr._on_participant_disconnected(
            MagicMock(identity="renderer_test-session")
        )

        handler.assert_awaited_once_with("renderer_test-session")

    @pytest.mark.asyncio
    async def test_reconnect_and_quality_events_are_dispatched(self, lk):
        mgr = _mgr(lk)
        reconnecting = AsyncMock()
        reconnected = AsyncMock()
        quality = AsyncMock()
        mgr.events.add("reconnecting", reconnecting)
        mgr.events.add("reconnected", reconnected)
        mgr.events.add("connection_quality_changed", quality)
        participant = MagicMock(identity="user_alice")

        await mgr._on_reconnecting()
        await mgr._on_reconnected()
        await mgr._on_connection_quality_changed(
            participant, rtc.ConnectionQuality.QUALITY_GOOD
        )

        reconnecting.assert_awaited_once_with()
        reconnected.assert_awaited_once_with()
        quality.assert_awaited_once_with(
            "user_alice", rtc.ConnectionQuality.QUALITY_GOOD
        )


class TestDataChannelEvents:
    @pytest.mark.asyncio
    async def test_data_packet_preserves_complete_envelope(self, lk):
        received = []
        _mgr(lk).events.add("data_channel_event", received.append)
        packet = MagicMock(
            topic="liveavatar",
            participant=MagicMock(identity="coordinator_test-session"),
            data=b'{"event":"session.state","requestId":"r1","responseId":"p1","seq":4,"timestamp":99,"data":{"state":"IDLE"}}',
        )

        await _mgr(lk)._on_data_received(packet)

        assert received == [
            DataChannelEvent(
                event="session.state",
                data={"state": "IDLE"},
                request_id="r1",
                response_id="p1",
                seq=4,
                timestamp=99,
                participant_identity="coordinator_test-session",
                topic="liveavatar",
            )
        ]

    @pytest.mark.asyncio
    async def test_arbitrary_topic_is_diagnostic_metadata_only(self, lk):
        handler = AsyncMock()
        _mgr(lk).events.add("data_channel_event", handler)

        await _mgr(lk)._on_data_received(
            MagicMock(
                topic="custom-observer-topic",
                participant=None,
                data=json.dumps({"event": "scene.ready"}).encode(),
            )
        )

        event = handler.await_args.args[0]
        assert event.event == "scene.ready"
        assert event.topic == "custom-observer-topic"

    @pytest.mark.asyncio
    async def test_resource_transition_packet_preserves_complete_envelope(self, lk):
        received = []
        _mgr(lk).events.add("data_channel_event", received.append)
        packet = MagicMock(
            topic="liveavatar",
            participant=MagicMock(identity="coordinator_test-session"),
            data=json.dumps(
                {
                    "event": "scene.resourceTransition",
                    "requestId": "renderer-req-1",
                    "timestamp": 1710000000000,
                    "data": {
                        "previousResourceId": "video-a",
                        "nextResourceId": "video-b",
                        "message": "switch from video-a to video-b",
                    },
                }
            ).encode(),
        )

        await _mgr(lk)._on_data_received(packet)

        assert received == [
            DataChannelEvent(
                event="scene.resourceTransition",
                data={
                    "previousResourceId": "video-a",
                    "nextResourceId": "video-b",
                    "message": "switch from video-a to video-b",
                },
                request_id="renderer-req-1",
                timestamp=1710000000000,
                participant_identity="coordinator_test-session",
                topic="liveavatar",
            )
        ]

    @pytest.mark.asyncio
    async def test_topicless_browser_system_event_is_dispatched(self, lk):
        handler = AsyncMock()
        _mgr(lk).events.add("data_channel_event", handler)

        await _mgr(lk)._on_data_received(MagicMock(
            topic="",
            participant=MagicMock(identity="user"),
            data=json.dumps({"event": "scene.ready"}).encode(),
        ))

        event = handler.await_args.args[0]
        assert event.event == "scene.ready"
        assert event.topic == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        [b"not-json", b"[]", b'{"event":4}', b"\xff"],
    )
    async def test_malformed_liveavatar_packet_dispatches_protocol_error(self, lk, data):
        errors = []
        _mgr(lk).events.add("protocol_error", errors.append)

        await _mgr(lk)._on_data_received(
            MagicMock(topic="liveavatar", participant=None, data=data)
        )

        assert len(errors) == 1
        assert isinstance(errors[0], DataChannelProtocolError)
        assert str(errors[0]).startswith("invalid liveavatar data packet:")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message",
        [
            {"event": "session.state", "data": {"state": 1}},
            {"event": "error", "data": {}},
            {"event": "scene.ready", "data": []},
            {"event": "scene.ready", "requestId": 1},
            {"event": "scene.ready", "responseId": False},
            {"event": "scene.ready", "seq": "1"},
            {"event": "scene.ready", "timestamp": True},
            {
                "event": "scene.resourceTransition",
                "data": {"nextResourceId": "video-b"},
            },
            {
                "event": "scene.resourceTransition",
                "data": {"previousResourceId": "   ", "nextResourceId": "video-b"},
            },
            {
                "event": "scene.resourceTransition",
                "data": {"previousResourceId": "video-a", "nextResourceId": ""},
            },
            {
                "event": "scene.resourceTransition",
                "data": {
                    "previousResourceId": "video-a",
                    "nextResourceId": "video-b",
                    "message": 123,
                },
            },
        ],
    )
    async def test_malformed_known_event_envelopes_emit_protocol_error_without_data_event(
        self, lk, message
    ):
        mgr = _mgr(lk)
        errors = []
        received = []
        mgr.events.add("protocol_error", errors.append)
        mgr.events.add("data_channel_event", received.append)

        await mgr._on_data_received(
            MagicMock(topic="liveavatar", participant=None, data=json.dumps(message).encode())
        )

        assert len(errors) == 1
        assert isinstance(errors[0], DataChannelProtocolError)
        assert received == []

    @pytest.mark.asyncio
    async def test_unknown_event_with_valid_envelope_is_preserved(self, lk):
        mgr = _mgr(lk)
        received = []
        mgr.events.add("data_channel_event", received.append)

        await mgr._on_data_received(
            MagicMock(
                topic="liveavatar", participant=None,
                data=b'{"event":"vendor.action","data":{"value":1},"seq":2}',
            )
        )

        assert received == [
            DataChannelEvent(
                event="vendor.action", data={"value": 1}, seq=2,
                participant_identity=None, topic="liveavatar",
            )
        ]


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
        publication = MagicMock(source=rtc.TrackSource.SOURCE_MICROPHONE)
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
        _stream_cls(lk).assert_called_once_with(
            track, sample_rate=16000, num_channels=1
        )

    @pytest.mark.asyncio
    async def test_republished_user_audio_replaces_old_consumer(self, lk):
        mgr = _mgr(lk)
        participant = MagicMock(identity="user_alice")
        publication = MagicMock(source=rtc.TrackSource.SOURCE_MICROPHONE)
        old_track = MagicMock(spec=["sid"])
        old_track.sid = "old"
        new_track = MagicMock(spec=["sid"])
        new_track.sid = "new"
        old_stream = AsyncMock()
        old_stream.__aiter__.return_value = []
        new_stream = AsyncMock()
        new_stream.__aiter__.return_value = []
        _stream_cls(lk).side_effect = [old_stream, new_stream]

        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            await mgr._on_track_subscribed(old_track, publication, participant)
            old_task = mgr._user_audio_task
            await mgr._on_track_subscribed(new_track, publication, participant)

        assert old_task.cancelled()
        old_stream.aclose.assert_awaited_once_with()
        assert mgr._user_audio_track_sid == "new"

    @pytest.mark.asyncio
    async def test_replacement_cancels_blocked_consumer_and_closes_stream(self, lk):
        mgr = _mgr(lk)
        participant = MagicMock(identity="user_alice")
        publication = MagicMock(source=rtc.TrackSource.SOURCE_MICROPHONE)
        old_track = MagicMock(sid="old")
        new_track = MagicMock(sid="new")
        started = asyncio.Event()

        class BlockingStream:
            def __init__(self):
                self.aclose = AsyncMock()

            def __aiter__(self):
                return self

            async def __anext__(self):
                started.set()
                await asyncio.Event().wait()

        old_stream = BlockingStream()
        new_stream = AsyncMock()
        new_stream.__aiter__.return_value = []
        _stream_cls(lk).side_effect = [old_stream, new_stream]

        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            await mgr._on_track_subscribed(old_track, publication, participant)
            old_task = mgr._user_audio_task
            await started.wait()
            await mgr._on_track_subscribed(new_track, publication, participant)

        assert old_task.cancelled()
        old_stream.aclose.assert_awaited_once_with()
        assert mgr._user_audio_track_sid == "new"

    @pytest.mark.asyncio
    async def test_concurrent_subscriptions_are_serialized(self, lk):
        mgr = _mgr(lk)
        participant = MagicMock(identity="user_alice")
        publication = MagicMock(source=rtc.TrackSource.SOURCE_MICROPHONE)
        first = MagicMock(sid="first")
        second = MagicMock(sid="second")
        streams = [AsyncMock(), AsyncMock()]
        for stream in streams:
            stream.__aiter__.return_value = []
        _stream_cls(lk).side_effect = streams
        first_dispatch_started = asyncio.Event()
        release_first = asyncio.Event()

        async def block_first(info):
            if info.track_sid == "first":
                first_dispatch_started.set()
                await release_first.wait()

        mgr.events.add("user_audio_track_subscribed", block_first)
        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            first_callback = asyncio.create_task(
                mgr._on_track_subscribed(first, publication, participant)
            )
            await first_dispatch_started.wait()
            second_callback = asyncio.create_task(
                mgr._on_track_subscribed(second, publication, participant)
            )
            await asyncio.sleep(0)
            assert not second_callback.done()
            release_first.set()
            await asyncio.gather(first_callback, second_callback)

        assert mgr._user_audio_track_sid == "second"
        streams[0].aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_stale_unsubscribe_does_not_clear_replacement(self, lk):
        mgr = _mgr(lk)
        current_stream = AsyncMock()
        mgr._user_audio_stream = current_stream
        mgr._user_audio_track_sid = "new"
        unsubscribed = AsyncMock()
        mgr.events.add("user_audio_track_unsubscribed", unsubscribed)

        await mgr._on_track_unsubscribed(
            MagicMock(sid="old"), MagicMock(), MagicMock()
        )

        assert mgr._user_audio_track_sid == "new"
        current_stream.aclose.assert_not_awaited()
        unsubscribed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_microphone_audio_is_skipped(self, lk):
        publication = MagicMock(source=rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO)
        participant = MagicMock(identity="user_alice")
        with patch("liveavatar_rtc.livekit_manager.isinstance", return_value=True):
            await _mgr(lk)._on_track_subscribed(
                MagicMock(), publication, participant
            )
        _stream_cls(lk).assert_not_called()

    @pytest.mark.asyncio
    async def test_track_mute_events_are_dispatched(self, lk):
        mgr = _mgr(lk)
        muted = AsyncMock()
        unmuted = AsyncMock()
        mgr.events.add("user_audio_track_muted", muted)
        mgr.events.add("user_audio_track_unmuted", unmuted)
        participant = MagicMock(identity="user_alice")
        publication = MagicMock(sid="TR_user")

        await mgr._on_track_muted(participant, publication)
        await mgr._on_track_unmuted(participant, publication)

        muted.assert_awaited_once_with("TR_user")
        unmuted.assert_awaited_once_with("TR_user")

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
        stream = AsyncMock()
        mgr._user_audio_stream = stream
        mgr._user_audio_track_sid = "TR_cleanup"

        track = MagicMock()
        track.sid = "TR_cleanup"
        await mgr._on_track_unsubscribed(track, MagicMock(), MagicMock())

        stream.aclose.assert_awaited_once_with()
        assert mgr._user_audio_track_sid is None

    @pytest.mark.asyncio
    async def test_user_departure_without_unsubscribe_closes_selected_audio(self, lk):
        mgr = _mgr(lk)
        stream = AsyncMock()
        consumer = asyncio.create_task(asyncio.Event().wait())
        mgr._user_audio_stream = stream
        mgr._user_audio_task = consumer
        mgr._user_audio_track_sid = "TR_cleanup"
        mgr._user_audio_participant_identity = "user_alice"
        unsubscribed = AsyncMock()
        mgr.events.add("user_audio_track_unsubscribed", unsubscribed)

        await mgr._on_participant_disconnected(MagicMock(identity="user_alice"))

        assert consumer.cancelled()
        stream.aclose.assert_awaited_once_with()
        assert mgr._user_audio_track_sid is None
        unsubscribed.assert_awaited_once_with("TR_cleanup")

    @pytest.mark.asyncio
    async def test_stale_user_departure_does_not_clear_replacement_audio(self, lk):
        mgr = _mgr(lk)
        stream = AsyncMock()
        mgr._user_audio_stream = stream
        mgr._user_audio_track_sid = "new"
        mgr._user_audio_participant_identity = "user_bob"

        await mgr._on_participant_disconnected(MagicMock(identity="user_alice"))

        assert mgr._user_audio_track_sid == "new"
        stream.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_track_unsubscribe_event_clears_session_audio_state(self, lk):
        mgr = _mgr(lk)
        session = Session(mgr)
        stream = AsyncMock()
        mgr._user_audio_stream = stream
        mgr._user_audio_track_sid = "TR_cleanup"
        await mgr.events.dispatch(
            "user_audio_track_subscribed",
            AudioTrackInfo(16000, 1, "user_alice", "TR_cleanup"),
        )
        assert session.is_user_audio_subscribed

        await mgr._on_track_unsubscribed(
            MagicMock(sid="TR_cleanup"), MagicMock(), MagicMock()
        )

        assert not session.is_user_audio_subscribed
        stream.aclose.assert_awaited_once_with()

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

        @mgr.events.on("data_channel_event")
        async def handler(event):
            events.append(event)

        packet = MagicMock(topic="liveavatar", participant=None)
        packet.data = json.dumps({"event": "test.event", "data": {"key": "val"}})
        await mgr._on_data_received(packet)
        assert events[0].event == "test.event"
        assert events[0].data == {"key": "val"}

    @pytest.mark.asyncio
    async def test_on_data_received_without_data_field(self, lk):
        mgr = _mgr(lk)
        events = []

        @mgr.events.on("data_channel_event")
        async def handler(event):
            events.append(event)

        packet = MagicMock(topic="liveavatar", participant=None)
        packet.data = json.dumps({"event": "test.event"})
        await mgr._on_data_received(packet)
        assert events[0].data == {}

    @pytest.mark.asyncio
    async def test_on_data_received_invalid_json(self, lk):
        packet = MagicMock(topic="liveavatar", participant=None)
        packet.data = "not valid json{{{"
        await _mgr(lk)._on_data_received(packet)  # Should not raise


class TestConsumeAudio:
    @pytest.mark.asyncio
    async def test_accepts_current_livekit_audio_frame_without_timestamp(self, lk):
        mgr = _mgr(lk)
        frames = []

        @mgr.events.on("user_audio_frame")
        async def handler(frame):
            frames.append(frame)

        pcm = np.array([1, 2, 3], dtype=np.int16)
        livekit_frame = rtc.AudioFrame(
            pcm.tobytes(), 16000, 1, len(pcm)
        )
        event = MagicMock(frame=livekit_frame)
        stream = AsyncMock()
        stream.__aiter__.return_value = [event]

        await mgr._consume_audio_stream("TR_current", stream)

        assert len(frames) == 1
        assert frames[0].timestamp == 0

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
    async def test_cancellation_is_propagated(self, lk):
        mgr = _mgr(lk)
        stream = AsyncMock()
        stream.__aiter__.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await mgr._consume_audio_stream("TR_test", stream)

    @pytest.mark.asyncio
    async def test_error_logged(self, lk, caplog):
        stream = AsyncMock()
        stream.__aiter__.side_effect = RuntimeError("stream broken")
        await _mgr(lk)._consume_audio_stream("TR_bad", stream)
        assert "Error consuming audio stream TR_bad" in caplog.text
