import asyncio

import numpy as np
import pytest

from liveavatar_rtc.errors import PromptStreamClosedError
from liveavatar_rtc.event_dispatcher import EventDispatcher
from liveavatar_rtc.session import RESPONSE_STATE, Session
from liveavatar_rtc.types import AudioFrame, DataChannelEvent, ResponseStateEvent


class RecordingManager:
    session_id = "session-1"
    sfu_url = "wss://sfu.test"
    user_token = "user-token"

    def __init__(self):
        self.events = EventDispatcher()
        self.sent = []
        self.registered_before_start = False
        self.session = None

    async def send_data_event(self, event):
        if event.event == "system.prompt.start":
            self.registered_before_start = event.response_id in self.session._responses
        self.sent.append(event)

    async def publish_audio_frame(self, frame):
        self.sent.append(frame)

    async def clear_output_queue(self):
        pass

    async def disconnect(self):
        pass


@pytest.fixture
def manager():
    return RecordingManager()


@pytest.fixture
def session(manager):
    value = Session(manager)
    manager.session = value
    return value


def lifecycle(seq, state, reason=None, request_id="request-1", response_id="response-1"):
    data = {"state": state}
    if reason is not None:
        data["reason"] = reason
    return DataChannelEvent(
        event="response.state",
        session_id="session-1",
        data=data,
        request_id=request_id,
        response_id=response_id,
        seq=seq,
        timestamp=1788960000000,
    )


@pytest.mark.asyncio
async def test_response_state_exposes_complete_event_and_unknown_values(session, manager):
    received = []
    session.on(RESPONSE_STATE)(received.append)

    await manager.events.dispatch(
        "data_channel_event", lifecycle(1, "FUTURE_STATE", "FUTURE_REASON")
    )

    assert received == [
        ResponseStateEvent(
            session_id="session-1",
            request_id="request-1",
            response_id="response-1",
            seq=1,
            timestamp=1788960000000,
            state="FUTURE_STATE",
            reason="FUTURE_REASON",
        )
    ]


@pytest.mark.asyncio
async def test_response_state_deduplicates_by_session_sequence(session, manager):
    received = []
    session.on(RESPONSE_STATE)(received.append)

    await manager.events.dispatch("data_channel_event", lifecycle(2, "ACCEPTED"))
    await manager.events.dispatch("data_channel_event", lifecycle(2, "FINISHED", "FAILED"))
    await manager.events.dispatch("data_channel_event", lifecycle(1, "FINISHED", "COMPLETED"))

    assert [event.state for event in received] == ["ACCEPTED"]


@pytest.mark.asyncio
async def test_first_matching_terminal_completes_response_once(session, manager):
    stream = await session.begin_prompt("request-1", "response-1")

    await manager.events.dispatch("data_channel_event", lifecycle(1, "ACCEPTED"))
    await manager.events.dispatch(
        "data_channel_event", lifecycle(2, "FINISHED", "USER_COMMAND_INTERRUPT")
    )
    await manager.events.dispatch("data_channel_event", lifecycle(3, "FINISHED", "COMPLETED"))

    terminal = await stream.wait_terminal()
    assert terminal.reason == "USER_COMMAND_INTERRUPT"
    assert stream.terminal is terminal


@pytest.mark.asyncio
async def test_identity_mismatch_does_not_complete_local_response(session, manager):
    stream = await session.begin_prompt("request-1", "response-1")
    await manager.events.dispatch(
        "data_channel_event", lifecycle(1, "FINISHED", "COMPLETED", request_id="other")
    )

    with pytest.raises(asyncio.TimeoutError):
        await stream.wait_terminal(timeout=0.01)


@pytest.mark.asyncio
async def test_prompt_registers_before_start_and_sends_atomic_chunk_sequence(session, manager):
    stream = await session.begin_prompt("request-1", "response-1")
    await asyncio.gather(*(stream.send(str(index)) for index in range(10)))
    await stream.done()

    assert manager.registered_before_start
    assert manager.sent[0] == DataChannelEvent(
        event="system.prompt.start", request_id="request-1", response_id="response-1"
    )
    chunks = [event for event in manager.sent if event.event == "system.prompt.chunk"]
    assert [event.seq for event in chunks] == list(range(1, 11))
    assert all(isinstance(event.timestamp, int) and event.timestamp > 0 for event in chunks)
    assert manager.sent[-1].event == "system.prompt.done"


@pytest.mark.asyncio
async def test_prompt_done_is_idempotent_but_send_after_done_fails(session, manager):
    stream = await session.begin_prompt("request-1", "response-1")
    await stream.done()
    await stream.done()

    with pytest.raises(PromptStreamClosedError):
        await stream.send("late")

    assert [event.event for event in manager.sent].count("system.prompt.done") == 1
    assert stream.terminal is None


@pytest.mark.asyncio
async def test_legacy_prompt_remains_one_shot(session, manager):
    await session.send_prompt("hello")
    assert manager.sent == [DataChannelEvent(event="system.prompt", data={"text": "hello"})]


@pytest.mark.asyncio
async def test_audio_response_establishes_identity_before_audio_and_finish_is_not_terminal(
    session, manager
):
    response = await session.begin_audio_response("request-1", "response-1")
    frame = AudioFrame(np.array([1], dtype=np.int16), 24000, 1)
    await response.send(frame)
    await response.done()

    assert manager.sent == [
        DataChannelEvent(
            event="response.audio.start", request_id="request-1", response_id="response-1"
        ),
        frame,
        DataChannelEvent(
            event="response.audio.finish", request_id="request-1", response_id="response-1"
        ),
    ]
    assert response.terminal is None


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_response(session):
    stream = await session.begin_prompt("request-1", "response-1")
    waiter = asyncio.create_task(stream.wait_terminal())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    await session._lk.events.dispatch("data_channel_event", lifecycle(1, "FINISHED", "COMPLETED"))
    assert (await stream.wait_terminal()).reason == "COMPLETED"


@pytest.mark.asyncio
async def test_sequence_deduplication_is_scoped_by_session(session, manager):
    received = []
    session.on(RESPONSE_STATE)(received.append)
    other = lifecycle(1, "ACCEPTED")
    other = DataChannelEvent(**{**vars(other), "session_id": "session-2"})

    await manager.events.dispatch("data_channel_event", lifecycle(1, "ACCEPTED"))
    await manager.events.dispatch("data_channel_event", other)

    assert [(event.session_id, event.seq) for event in received] == [
        ("session-1", 1),
        ("session-2", 1),
    ]
