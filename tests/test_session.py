import asyncio
from types import SimpleNamespace
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
from liveavatar_rtc.types import (
    AudioFrame,
    AudioTrackInfo,
    DataChannelEvent,
    FrontendConnection,
)


@pytest.fixture
def manager():
    manager = MagicMock()
    type(manager).session_id = PropertyMock(return_value="sess-test-123")
    type(manager).sfu_url = PropertyMock(return_value="wss://sfu.test.com")
    type(manager).user_token = PropertyMock(return_value="user-tok-test")
    manager.events = EventDispatcher()
    manager.publish_audio_frame = AsyncMock()
    manager.clear_output_queue = AsyncMock()
    manager.send_data_event = AsyncMock()
    manager.disconnect = AsyncMock()
    return manager


@pytest.fixture
def session(manager):
    return Session(manager)


def test_rtc_public_surface_excludes_platform_tts_and_text(manager):
    import liveavatar_rtc

    expected_exports = {
        "PlatformRTCClient",
        "Session",
        "AudioFrame",
        "AudioTrackInfo",
        "FrontendConnection",
        "DataChannelEvent",
        "USER_AUDIO_FRAME",
        "SCENE_READY",
        "DISCONNECTED",
    }
    assert expected_exports.issubset(set(liveavatar_rtc.__all__))

    removed_exports = {"TTSConfig", "INPUT_TEXT"}
    assert removed_exports.isdisjoint(set(liveavatar_rtc.__all__))

    removed_methods = {
        "send_response_start",
        "send_response_chunk",
        "send_response_done",
        "send_prompt",
        "send_response_audio_prompt_start",
        "send_response_audio_prompt_finish",
    }
    assert removed_methods.isdisjoint(set(dir(liveavatar_rtc.Session)))
    assert "connection" not in vars(liveavatar_rtc.Session(manager)).keys()


def test_initial_state_and_connection_metadata(session):
    assert session.session_id == "sess-test-123"
    assert session.sfu_url == "wss://sfu.test.com"
    assert session.user_token == "user-tok-test"
    assert session.frontend_connection == FrontendConnection(
        user_token="user-tok-test", sfu_url="wss://sfu.test.com"
    )
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
async def test_completed_stream_cleanup_does_not_release_new_stream_ownership(
    session, manager, monkeypatch
):
    real_create_task = asyncio.create_task
    release_first_cleanup = asyncio.Event()
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    captures = 0
    max_captures = 0

    class DelayedCompletion:
        def __init__(self, coroutine):
            self.task = real_create_task(coroutine)

        def done(self):
            return self.task.done()

        def __await__(self):
            async def wait():
                await self.task
                await release_first_cleanup.wait()

            return wait().__await__()

    first_child = None

    def create_task(coroutine):
        nonlocal first_child
        if first_child is None:
            first_child = DelayedCompletion(coroutine)
            return first_child
        return real_create_task(coroutine)

    import liveavatar_rtc.session as session_module

    monkeypatch.setattr(
        session_module,
        "asyncio",
        SimpleNamespace(create_task=create_task, CancelledError=asyncio.CancelledError),
    )

    async def capture(frame):
        nonlocal captures, max_captures
        captures += 1
        max_captures = max(max_captures, captures)
        try:
            if int(frame.data[0]) == 2:
                second_started.set()
                await release_second.wait()
        finally:
            captures -= 1

    async def frames(value):
        yield AudioFrame.from_pcm(value.to_bytes(2, "little", signed=True), 24000)

    manager.publish_audio_frame.side_effect = capture
    first = real_create_task(session.publish_audio_stream(frames(1)))
    while first_child is None or not first_child.done():
        await asyncio.sleep(0)

    second = real_create_task(session.publish_audio_stream(frames(2)))
    await second_started.wait()
    release_first_cleanup.set()
    await first

    with pytest.raises(AudioPublishError, match="already active"):
        await session.publish_audio_stream(frames(3))

    assert max_captures == 1
    release_second.set()
    await second


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
@pytest.mark.parametrize(
    "sender,args",
    [
        ("send_custom_event", ("vendor.action",)),
        ("send_voice_start", ("req",)),
        ("send_asr_partial", ("req", "text", 1)),
        ("send_voice_finish", ("req",)),
        ("send_asr_final", ("req", "text")),
        ("send_subtitle", ("req", "resp", "text", 1, 2)),
    ],
)
async def test_send_helpers_reject_closing_session_with_typed_error(
    session, manager, sender, args
):
    session._closing = True

    with pytest.raises(SessionClosedError):
        await getattr(session, sender)(*args)

    manager.send_data_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_is_idempotent(session, manager):
    await session.close()
    await session.close()
    manager.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_cancels_stream_sends_control_and_emits_local_event(
    session, manager
):
    interrupted = []
    started = asyncio.Event()

    async def blocking_frames():
        started.set()
        await asyncio.Event().wait()
        yield AudioFrame.from_pcm(b"\x00\x00", 24000)

    session.on("interrupted")(lambda request_id: interrupted.append(request_id))
    stream_task = asyncio.create_task(session.publish_audio_stream(blocking_frames()))
    await started.wait()

    await session.interrupt("req-9")

    with pytest.raises(asyncio.CancelledError):
        await stream_task
    manager.clear_output_queue.assert_awaited_once_with()
    manager.send_data_event.assert_awaited_once_with(
        DataChannelEvent(event="control.interrupt", request_id="req-9")
    )
    assert interrupted == ["req-9"]


@pytest.mark.asyncio
async def test_interrupt_caller_cancellation_is_not_swallowed(session, manager):
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def blocking_frames():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
        yield AudioFrame.from_pcm(b"\x00\x00", 24000)

    stream_task = asyncio.create_task(session.publish_audio_stream(blocking_frames()))
    await started.wait()
    interrupt_task = asyncio.create_task(session.interrupt("req-cancelled"))
    await cleanup_started.wait()

    interrupt_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await interrupt_task

    manager.clear_output_queue.assert_not_awaited()
    manager.send_data_event.assert_not_awaited()
    assert not stream_task.done()
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await stream_task


@pytest.mark.asyncio
async def test_close_cancels_active_stream_and_emits_closed_once(session, manager):
    closed = []
    started = asyncio.Event()

    async def blocking_frames():
        started.set()
        await asyncio.Event().wait()
        yield AudioFrame.from_pcm(b"\x00\x00", 24000)

    session.on("closed")(lambda: closed.append(True))
    stream_task = asyncio.create_task(session.publish_audio_stream(blocking_frames()))
    await started.wait()

    await asyncio.gather(session.close(), session.close())

    with pytest.raises(asyncio.CancelledError):
        await stream_task
    manager.disconnect.assert_awaited_once_with()
    assert closed == [True]


@pytest.mark.asyncio
async def test_close_preserves_disconnect_error_when_closed_handler_fails(
    session, manager
):
    manager.disconnect.side_effect = RuntimeError("disconnect failed")

    @session.on("closed")
    async def fail_closed_handler():
        raise ValueError("handler failed")

    with pytest.raises(RuntimeError, match="disconnect failed"):
        await session.close()

    assert session.is_closed


@pytest.mark.asyncio
async def test_close_callers_wait_for_blocked_closed_handler(session):
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()

    @session.on("closed")
    async def block_closed_handler():
        handler_started.set()
        await release_handler.wait()

    first = asyncio.create_task(session.close())
    await handler_started.wait()
    second = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    assert not second.done()
    release_handler.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_close_after_remote_disconnect_waits_for_active_shutdown(session, manager):
    disconnect_started = asyncio.Event()
    release_disconnect = asyncio.Event()

    async def block_disconnect():
        disconnect_started.set()
        await release_disconnect.wait()

    manager.disconnect.side_effect = block_disconnect
    first = asyncio.create_task(session.close())
    await disconnect_started.wait()
    await manager.events.dispatch("disconnected", "remote close")
    second = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    assert session.is_closed
    assert not second.done()
    release_disconnect.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_closed_handler_can_reenter_close_without_self_await(session):
    handler_returned = asyncio.Event()

    @session.on("closed")
    async def close_again():
        await session.close()
        handler_returned.set()

    await asyncio.wait_for(session.close(), timeout=0.1)

    assert handler_returned.is_set()
