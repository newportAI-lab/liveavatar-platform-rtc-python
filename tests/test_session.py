import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import numpy as np
import pytest

from liveavatar_rtc.errors import (
    AudioFormatError,
    AudioPublishError,
    SessionClosedError,
    SessionWaitTimeoutError,
)
from liveavatar_rtc.event_dispatcher import EventDispatcher
from liveavatar_rtc.session import Session
from liveavatar_rtc.types import AudioFrame, AudioTrackInfo, DataChannelEvent


@pytest.fixture
def manager():
    manager = MagicMock()
    type(manager).session_id = PropertyMock(return_value="sess-test-123")
    type(manager).sfu_url = PropertyMock(return_value="wss://sfu.test.com")
    type(manager).user_token = PropertyMock(return_value="user-tok-test")
    manager.events = EventDispatcher()
    manager.publish_audio_frame = AsyncMock()
    manager.send_data_event = AsyncMock()
    manager.disconnect = AsyncMock()
    return manager


@pytest.fixture
def session(manager):
    return Session(manager)


def test_initial_state_and_connection_metadata(session):
    assert session.session_id == "sess-test-123"
    assert session.sfu_url == "wss://sfu.test.com"
    assert session.user_token == "user-tok-test"
    assert session.is_agent_connected
    assert not session.is_user_joined
    assert not session.is_user_audio_subscribed
    assert not session.is_scene_ready
    assert not session.is_closing
    assert not session.is_closed


@pytest.mark.asyncio
async def test_scene_ready_sets_state_and_resolves_waiter(session, manager):
    received = []

    @session.on("scene.ready")
    async def record(envelope):
        received.append(envelope)

    waiter = asyncio.create_task(session.wait_for_scene_ready(timeout=0.1))

    envelope = DataChannelEvent(event="scene.ready", topic="liveavatar")
    await manager.events.dispatch("data_channel_event", envelope)

    await waiter
    assert session.is_scene_ready
    assert received == [envelope]


@pytest.mark.asyncio
async def test_duplicate_scene_ready_is_idempotent(session, manager):
    received = []

    @session.on("scene.ready")
    async def record(envelope):
        received.append(envelope)

    envelope = DataChannelEvent(event="scene.ready", topic="liveavatar")

    await manager.events.dispatch("data_channel_event", envelope)
    await manager.events.dispatch("data_channel_event", envelope)

    assert received == [envelope]


@pytest.mark.asyncio
async def test_unknown_data_event_is_forwarded_as_custom_event(session, manager):
    received = []

    @session.on("custom_event")
    async def record(envelope):
        received.append(envelope)

    envelope = DataChannelEvent(
        event="vendor.action", data={"value": 1}, request_id="req-1", seq=2
    )

    await manager.events.dispatch("data_channel_event", envelope)

    assert received == [envelope]


@pytest.mark.asyncio
async def test_participant_and_track_events_update_state(session, manager):
    user = asyncio.create_task(session.wait_for_user(timeout=0.1))
    await manager.events.dispatch("user_joined", "user_alice")
    await user
    assert session.is_user_joined

    info = AudioTrackInfo(16000, 1, "user_alice", "TR_1")
    audio = asyncio.create_task(session.wait_for_user_audio(timeout=0.1))
    await manager.events.dispatch("user_audio_track_subscribed", info)
    await audio
    assert session.is_user_audio_subscribed

    await manager.events.dispatch("user_audio_track_unsubscribed", "TR_1")
    await manager.events.dispatch("user_left", "user_alice")
    assert not session.is_user_audio_subscribed
    assert not session.is_user_joined


@pytest.mark.asyncio
async def test_waiters_return_immediately_for_satisfied_state(session, manager):
    await manager.events.dispatch("user_joined", "user_alice")
    await manager.events.dispatch(
        "user_audio_track_subscribed", AudioTrackInfo(16000, 1, "user_alice", "TR_1")
    )
    await manager.events.dispatch(
        "data_channel_event", DataChannelEvent(event="scene.ready")
    )
    await session.wait_for_user(timeout=0)
    await session.wait_for_user_audio(timeout=0)
    await session.wait_for_scene_ready(timeout=0)


@pytest.mark.asyncio
async def test_waiter_fails_when_session_closes(session):
    waiter = asyncio.create_task(session.wait_for_user(timeout=10))
    await asyncio.sleep(0)
    await session.close()
    with pytest.raises(SessionClosedError):
        await waiter


@pytest.mark.asyncio
async def test_waiter_raises_typed_timeout(session):
    with pytest.raises(SessionWaitTimeoutError, match="scene_ready"):
        await session.wait_for_scene_ready(timeout=0.01)


@pytest.mark.asyncio
async def test_disconnected_closes_session_and_resolves_waiters(session, manager):
    waiter = asyncio.create_task(session.wait_for_user(timeout=10))
    await asyncio.sleep(0)
    await manager.events.dispatch("disconnected", "room closed")
    with pytest.raises(SessionClosedError):
        await waiter
    assert session.is_closed
    assert not session.is_agent_connected


@pytest.mark.asyncio
async def test_publish_audio_delegates(session, manager):
    frame = AudioFrame(np.array([0], dtype=np.int16), 24000, 1)
    await session.publish_audio(frame)
    manager.publish_audio_frame.assert_awaited_once_with(frame)


@pytest.mark.asyncio
async def test_publish_stream_preserves_order(session, manager):
    published = []

    async def capture(frame):
        published.append(int(frame.data[0]))

    async def frames():
        for value in (1, 2, 3):
            yield AudioFrame.from_pcm(value.to_bytes(2, "little", signed=True), 24000)

    manager.publish_audio_frame.side_effect = capture

    await session.publish_audio_stream(frames())

    assert published == [1, 2, 3]


@pytest.mark.asyncio
async def test_publish_stream_rejects_second_active_stream(session, manager):
    started = asyncio.Event()
    release = asyncio.Event()

    async def capture(frame):
        started.set()
        await release.wait()

    async def frames():
        yield AudioFrame.from_pcm(b"\x01\x00", 24000)

    manager.publish_audio_frame.side_effect = capture
    first = asyncio.create_task(session.publish_audio_stream(frames()))
    await started.wait()

    with pytest.raises(AudioPublishError, match="already active"):
        await session.publish_audio_stream(frames())

    release.set()
    await first


@pytest.mark.asyncio
async def test_publish_stream_dispatches_typed_failure(session, manager):
    errors = []

    @session.on("error")
    async def record(error):
        errors.append(error)

    async def frames():
        yield AudioFrame.from_pcm(b"\x01\x00", 24000)

    manager.publish_audio_frame.side_effect = RuntimeError("capture failed")

    with pytest.raises(AudioPublishError, match="failed to publish") as caught:
        await session.publish_audio_stream(frames())

    assert errors == [caught.value]
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_publish_stream_preserves_typed_format_failure(session, manager):
    async def frames():
        yield AudioFrame.from_pcm(b"\x01\x00", 16000)

    manager.publish_audio_frame.side_effect = AudioFormatError("must be 24000")

    with pytest.raises(AudioFormatError, match="24000"):
        await session.publish_audio_stream(frames())


@pytest.mark.asyncio
async def test_publish_after_close_fails(session, manager):
    await session.close()

    with pytest.raises(SessionClosedError):
        await session.publish_audio(AudioFrame.from_pcm(b"\x00\x00", 24000))

    manager.publish_audio_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_stream_after_close_fails(session):
    async def frames():
        yield AudioFrame.from_pcm(b"\x00\x00", 24000)

    await session.close()

    with pytest.raises(SessionClosedError):
        await session.publish_audio_stream(frames())


@pytest.mark.asyncio
async def test_observability_helpers_preserve_correlation_fields(session, manager):
    await session.send_voice_start("req-1")
    await session.send_asr_partial("req-1", "hel", 1)
    await session.send_voice_finish("req-1")
    await session.send_asr_final("req-1", "hello")
    await session.send_subtitle("req-1", "resp-1", "caption", 2, 1234)

    assert [call.args[0] for call in manager.send_data_event.await_args_list] == [
        DataChannelEvent(event="input.voice.start", request_id="req-1"),
        DataChannelEvent(
            event="input.asr.partial", data={"text": "hel"}, request_id="req-1", seq=1
        ),
        DataChannelEvent(event="input.voice.finish", request_id="req-1"),
        DataChannelEvent(
            event="input.asr.final", data={"text": "hello"}, request_id="req-1"
        ),
        DataChannelEvent(
            event="response.chunk",
            data={"text": "caption"},
            request_id="req-1",
            response_id="resp-1",
            seq=2,
            timestamp=1234,
        ),
    ]


@pytest.mark.asyncio
async def test_send_custom_event_preserves_envelope(session, manager):
    await session.send_custom_event(
        "vendor.action", {"value": 1}, "req-1", "resp-1", 2, 1234
    )
    manager.send_data_event.assert_awaited_once_with(
        DataChannelEvent(
            event="vendor.action",
            data={"value": 1},
            request_id="req-1",
            response_id="resp-1",
            seq=2,
            timestamp=1234,
        )
    )


@pytest.mark.asyncio
async def test_close_is_idempotent(session, manager):
    await session.close()
    await session.close()
    manager.disconnect.assert_awaited_once()
