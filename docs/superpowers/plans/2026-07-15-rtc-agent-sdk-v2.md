# RTC Agent SDK v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a breaking RTC Agent - Platform RTC SDK that cleanly separates session startup, room readiness, scene readiness, inbound/outbound audio formats, typed lifecycle events, stream interruption, and deterministic cleanup.

**Architecture:** Retain the existing `PlatformRTCClient -> Session -> LiveKitManager` layering. Add focused public models and errors in `types.py`/`errors.py`; keep REST ownership in `ApiClient`, LiveKit ownership in `LiveKitManager`, and developer-facing state, waiters, events, and stream publishing in `Session`.

**Tech Stack:** Python 3.10+, asyncio, dataclasses, httpx, LiveKit Python SDK >=1.0, NumPy >=1.24, pytest with mocked LiveKit objects.

## Global Constraints

- Scope is RTC Agent - Platform RTC only.
- Do not implement BYO RTC, multiple users/tracks, or multiple Avatars/Agents.
- `/v1/session/start` always sends `mode: "rtcAgent"`.
- Remove `voiceId`, platform TTS, platform text input, and compatibility shims.
- Default input sample rate is 16,000 Hz; default output sample rate is 24,000 Hz.
- A server-returned output sample rate overrides the client default.
- Output is mono PCM16; LiveKit owns RTC processing and Opus encoding.
- User identity remains permissive through `identity.startswith("user")`.
- Process Data Channel packets only on topic `liveavatar`.
- Preserve unrelated untracked `.codegraph/` and `ragflow/` content.
- Follow strict TDD: add a failing focused test, observe failure, implement minimally, rerun focused and regression tests, then commit.

## File Structure

- Create `src/liveavatar_rtc/errors.py`: public structured exception hierarchy.
- Modify `src/liveavatar_rtc/types.py`: audio validation, frontend connection, start result, and Data Channel envelope models; remove `TTSConfig`.
- Modify `src/liveavatar_rtc/api_client.py`: explicit RTC mode, output sample-rate parsing, no voice configuration.
- Modify `src/liveavatar_rtc/livekit_manager.py`: split sample rates, participant/track states, complete Data Channel envelopes, connection events, output queue control, and deterministic cleanup.
- Modify `src/liveavatar_rtc/session.py`: public state, waiters, typed events, audio streaming, interruption, custom events, and removed legacy APIs.
- Modify `src/liveavatar_rtc/client.py`: new constructor, immediate Agent-connect semantics, frontend-safe result exposure, and shared cleanup.
- Modify `src/liveavatar_rtc/__init__.py`: v2 public exports only.
- Modify `tests/test_types.py`, `tests/test_api_client.py`, `tests/test_livekit_manager.py`, `tests/test_session.py`, and `tests/test_client.py`: replace legacy expectations and cover the v2 contract.
- Modify `examples/basic_agent.py`, `README.md`, and `README.zh.md`: document developer-owned ASR/LLM/TTS RTC flow.

---

### Task 1: Public Models and Structured Errors

**Files:**
- Create: `src/liveavatar_rtc/errors.py`
- Modify: `src/liveavatar_rtc/types.py`
- Modify: `src/liveavatar_rtc/__init__.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Consumes: NumPy `ndarray` audio samples.
- Produces: `RTCSDKError`, `APIError`, `SessionStartError`, `RTCConnectionError`, `SessionClosedError`, `SessionWaitTimeoutError`, `AudioFormatError`, `AudioPublishError`, `DataChannelProtocolError`, `FrontendConnection`, `SessionInfo`, `DataChannelEvent`, and validated `AudioFrame`.

- [ ] **Step 1: Replace legacy type tests with failing v2 model and error tests**

```python
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
```

- [ ] **Step 2: Run the focused tests and observe missing v2 symbols**

Run: `pytest -q tests/test_types.py`

Expected: FAIL during import because `AudioFormatError`, `DataChannelEvent`, and `FrontendConnection` do not exist.

- [ ] **Step 3: Add the exception hierarchy and public models**

```python
# src/liveavatar_rtc/errors.py
class RTCSDKError(Exception):
    """Base exception for the RTC Agent SDK."""


class APIError(RTCSDKError):
    def __init__(self, code: int | str | None, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"API error {code}: {message}")


class SessionStartError(RTCSDKError):
    pass


class RTCConnectionError(RTCSDKError):
    pass


class SessionClosedError(RTCSDKError):
    pass


class SessionWaitTimeoutError(RTCSDKError):
    pass


class AudioFormatError(RTCSDKError):
    pass


class AudioPublishError(RTCSDKError):
    pass


class DataChannelProtocolError(RTCSDKError):
    pass
```

```python
# additions/replacements in src/liveavatar_rtc/types.py
from dataclasses import dataclass, field
from typing import Any

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


def validate_for_output(self, output_sample_rate: int) -> None:
    if self.data.dtype != np.int16:
        raise AudioFormatError("output audio must use int16 PCM samples")
    if self.num_channels != 1 or self.data.ndim != 1:
        raise AudioFormatError("output audio must be mono")
    if self.sample_rate != output_sample_rate:
        raise AudioFormatError(
            f"output sample rate must be {output_sample_rate}, got {self.sample_rate}"
        )
```

Remove `TTSConfig`, attach `validate_for_output` as an `AudioFrame` method, and export every public v2 symbol from `src/liveavatar_rtc/__init__.py`.

- [ ] **Step 4: Run model tests**

Run: `pytest -q tests/test_types.py`

Expected: PASS.

- [ ] **Step 5: Commit the public contract**

```bash
git add src/liveavatar_rtc/errors.py src/liveavatar_rtc/types.py src/liveavatar_rtc/__init__.py tests/test_types.py
git commit -m "feat: define rtc agent v2 models and errors"
```

---

### Task 2: Explicit RTC Session Start Contract

**Files:**
- Modify: `src/liveavatar_rtc/api_client.py`
- Test: `tests/test_api_client.py`

**Interfaces:**
- Consumes: `avatar_id: str`.
- Produces: `ApiClient.start_session(avatar_id: str) -> SessionInfo` with optional `output_sample_rate`.

- [ ] **Step 1: Write failing request and response tests**

```python
@pytest.mark.asyncio
async def test_start_session_sends_rtc_agent_mode(api_client, mock_transport):
    mock_transport.respond_json({
        "code": 0,
        "data": {
            "sessionId": "s1",
            "agentToken": "agent",
            "userToken": "user",
            "sfuUrl": "wss://sfu",
            "outputSampleRate": 24000,
        },
    })
    info = await api_client.start_session("avatar-1")
    assert mock_transport.last_json == {"avatarId": "avatar-1", "mode": "rtcAgent"}
    assert info.output_sample_rate == 24000


def test_start_session_has_no_voice_id_parameter():
    assert "voice_id" not in inspect.signature(ApiClient.start_session).parameters
```

- [ ] **Step 2: Run focused tests and observe the old request shape**

Run: `pytest -q tests/test_api_client.py`

Expected: FAIL because the request omits `mode` and the method still accepts `voice_id`.

- [ ] **Step 3: Implement the breaking REST contract**

```python
async def start_session(self, avatar_id: str) -> SessionInfo:
    resp = await self._client.post(
        "/v1/session/start",
        headers=self._headers(),
        json={"avatarId": avatar_id, "mode": "rtcAgent"},
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise APIError(payload.get("code"), payload.get("message", "unknown error"))
    data = payload.get("data") or {}
    session_id = data.get("sessionId", "")
    sfu_url = data.get("sfuUrl", "")
    agent_token = data.get("agentToken", "")
    if not session_id or not sfu_url or not agent_token:
        raise SessionStartError("session response is missing sessionId, sfuUrl, or agentToken")
    return SessionInfo(
        session_id=session_id,
        agent_token=agent_token,
        user_token=data.get("userToken", ""),
        sfu_url=sfu_url,
        output_sample_rate=data.get("outputSampleRate"),
    )
```

Keep Bearer authentication, sandbox headers, HTTP failure coverage, and `/session/stop` behavior.

- [ ] **Step 4: Run API tests**

Run: `pytest -q tests/test_api_client.py`

Expected: PASS.

- [ ] **Step 5: Commit the REST contract**

```bash
git add src/liveavatar_rtc/api_client.py tests/test_api_client.py
git commit -m "feat: start explicit rtc agent sessions"
```

---

### Task 3: LiveKit Connection, Participant, and Track State

**Files:**
- Modify: `src/liveavatar_rtc/livekit_manager.py`
- Test: `tests/test_livekit_manager.py`

**Interfaces:**
- Consumes: `input_sample_rate`, `output_sample_rate`, Agent token, and LiveKit room events.
- Produces: immediate Agent connection, participant events, one deterministic user-audio consumer, and reconnect/quality events.

- [ ] **Step 1: Add failing connection and lifecycle tests**

```python
@pytest.mark.asyncio
async def test_connect_publishes_output_track_without_waiting_for_user(manager, room):
    await asyncio.wait_for(manager.connect(), timeout=0.1)
    room.connect.assert_awaited_once()
    room.local_participant.publish_track.assert_awaited_once()


@pytest.mark.asyncio
async def test_participant_roles_are_dispatched(manager):
    seen = []
    manager.events.add("renderer_joined", lambda identity: seen.append(identity))
    await manager._on_participant_connected(FakeParticipant("renderer_s1"))
    assert seen == ["renderer_s1"]


@pytest.mark.asyncio
async def test_user_republished_audio_replaces_old_consumer(manager, livekit):
    await manager._on_track_subscribed(livekit.audio("old"), livekit.pub("old"), livekit.user())
    old_task = manager._user_audio_task
    await manager._on_track_subscribed(livekit.audio("new"), livekit.pub("new"), livekit.user())
    assert old_task.cancelled()
    assert manager._user_audio_track_sid == "new"
```

- [ ] **Step 2: Run focused LiveKit tests and observe missing split-state behavior**

Run: `pytest -q tests/test_livekit_manager.py`

Expected: FAIL because the manager has one sample rate, no role events, and per-SID consumers.

- [ ] **Step 3: Implement split rates and deterministic role/track handling**

```python
def __init__(
    self,
    session_id: str,
    sfu_url: str,
    agent_token: str,
    user_token: str = "",
    input_sample_rate: int = 16000,
    output_sample_rate: int = 24000,
) -> None:
    self._input_sample_rate = input_sample_rate
    self._output_sample_rate = output_sample_rate
    self._user_audio_stream = None
    self._user_audio_task = None
    self._user_audio_track_sid = None
```

```python
def _is_user_identity(self, identity: str) -> bool:
    return identity.startswith("user")


async def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
    identity = participant.identity
    if self._is_user_identity(identity):
        await self.events.dispatch("user_joined", identity)
    elif identity == f"coordinator_{self._session_id}":
        await self.events.dispatch("coordinator_joined", identity)
    elif identity == f"renderer_{self._session_id}":
        await self.events.dispatch("renderer_joined", identity)
```

Construct inbound `rtc.AudioStream` at `input_sample_rate` and outbound
`rtc.AudioSource` at `output_sample_rate`. Add participant-disconnected,
track-muted/unmuted, reconnected, and connection-quality callbacks supported by
LiveKit >=1.0. Keep source checks behind `getattr(publication, "source", None)` so
mock and SDK version differences remain safe.

- [ ] **Step 4: Run LiveKit lifecycle tests**

Run: `pytest -q tests/test_livekit_manager.py`

Expected: PASS for connection, role, track replacement, unsubscribe, mute,
unmute, reconnecting, reconnected, disconnected, and quality cases.

- [ ] **Step 5: Commit room lifecycle handling**

```bash
git add src/liveavatar_rtc/livekit_manager.py tests/test_livekit_manager.py
git commit -m "feat: expose rtc room and track lifecycle"
```

---

### Task 4: Complete Data Channel Envelopes

**Files:**
- Modify: `src/liveavatar_rtc/livekit_manager.py`
- Test: `tests/test_livekit_manager.py`

**Interfaces:**
- Consumes: LiveKit `DataPacket` and outbound `DataChannelEvent` fields.
- Produces: `data_channel_event` with the complete envelope and
  `send_data_event(...)` on topic `liveavatar`.

- [ ] **Step 1: Add failing topic, envelope, malformed, and send tests**

```python
@pytest.mark.asyncio
async def test_data_packet_preserves_envelope(manager):
    seen = []
    manager.events.add("data_channel_event", lambda event: seen.append(event))
    packet = FakeDataPacket(
        topic="liveavatar",
        participant_identity="coordinator_s1",
        data=b'{"event":"session.state","requestId":"r1","seq":4,"timestamp":99,"data":{"state":"IDLE"}}',
    )
    await manager._on_data_received(packet)
    assert seen[0].request_id == "r1"
    assert seen[0].seq == 4
    assert seen[0].participant_identity == "coordinator_s1"


@pytest.mark.asyncio
async def test_non_liveavatar_topic_is_ignored(manager):
    await manager._on_data_received(FakeDataPacket(topic="other", data=b'{}'))
    assert manager.events_dispatch_count == 0
```

- [ ] **Step 2: Run Data Channel tests and observe envelope loss**

Run: `pytest -q tests/test_livekit_manager.py -k 'data_packet or data_event or topic'`

Expected: FAIL because the current manager dispatches only `event` and `data`.

- [ ] **Step 3: Parse and send complete events**

```python
async def _on_data_received(self, packet: rtc.DataPacket) -> None:
    if packet.topic != DATA_TOPIC:
        return
    try:
        message = json.loads(packet.data)
        if not isinstance(message, dict) or not isinstance(message.get("event"), str):
            raise ValueError("event must be a string")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        error = DataChannelProtocolError(f"invalid liveavatar data packet: {exc}")
        await self.events.dispatch("protocol_error", error)
        return
    participant = getattr(packet, "participant", None)
    envelope = DataChannelEvent(
        event=message["event"],
        data=message.get("data") or {},
        request_id=message.get("requestId"),
        response_id=message.get("responseId"),
        seq=message.get("seq"),
        timestamp=message.get("timestamp"),
        participant_identity=getattr(participant, "identity", None),
        topic=packet.topic,
    )
    await self.events.dispatch("data_channel_event", envelope)
```

Implement `send_data_event()` to omit only fields whose value is `None` and
publish reliable JSON on `DATA_TOPIC`.

- [ ] **Step 4: Run all LiveKit manager tests**

Run: `pytest -q tests/test_livekit_manager.py`

Expected: PASS.

- [ ] **Step 5: Commit the Data Channel contract**

```bash
git add src/liveavatar_rtc/livekit_manager.py tests/test_livekit_manager.py
git commit -m "feat: preserve rtc data channel envelopes"
```

---

### Task 5: Session State, Scene Readiness, and Waiters

**Files:**
- Modify: `src/liveavatar_rtc/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `LiveKitManager.events` and `DataChannelEvent`.
- Produces: state properties, `wait_for_user`, `wait_for_user_audio`,
  `wait_for_scene_ready`, typed event forwarding, and `send_custom_event`.

- [ ] **Step 1: Add failing state and waiter tests**

```python
@pytest.mark.asyncio
async def test_scene_ready_sets_state_and_resolves_waiter(session, manager):
    waiter = asyncio.create_task(session.wait_for_scene_ready(timeout=0.1))
    await manager.events.dispatch(
        "data_channel_event",
        DataChannelEvent(event="scene.ready", topic="liveavatar"),
    )
    await waiter
    assert session.is_scene_ready


@pytest.mark.asyncio
async def test_waiter_fails_when_session_closes(session):
    waiter = asyncio.create_task(session.wait_for_user(timeout=10))
    await session.close()
    with pytest.raises(SessionClosedError):
        await waiter


@pytest.mark.asyncio
async def test_waiter_raises_typed_timeout(session):
    with pytest.raises(SessionWaitTimeoutError, match="scene_ready"):
        await session.wait_for_scene_ready(timeout=0.01)
```

- [ ] **Step 2: Run Session tests and observe missing state/waiters**

Run: `pytest -q tests/test_session.py`

Expected: FAIL because scene readiness is only an untyped forwarded dictionary.

- [ ] **Step 3: Implement state events and close-aware waiters**

```python
async def _wait_for(self, event: asyncio.Event, name: str, timeout: float) -> None:
    if self._closed:
        raise SessionClosedError(f"session {self.session_id} is closed")
    event_task = asyncio.create_task(event.wait())
    close_task = asyncio.create_task(self._closed_event.wait())
    done, pending = await asyncio.wait(
        {event_task, close_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    if close_task in done:
        raise SessionClosedError(f"session {self.session_id} closed while waiting for {name}")
    if event_task not in done:
        raise SessionWaitTimeoutError(f"timed out waiting for {name}")
```

Bridge participant and track events to state setters. Dispatch known Data Channel
events by their protocol event name with the full `DataChannelEvent`; dispatch
unknown events as `custom_event`. Make duplicate `scene.ready` idempotent.

Retain developer-owned observability helpers with complete correlation fields:

```python
async def send_voice_start(self, request_id: str) -> None:
    await self._lk.send_data_event("input.voice.start", request_id=request_id)


async def send_asr_partial(self, request_id: str, text: str, seq: int) -> None:
    await self._lk.send_data_event(
        "input.asr.partial", data={"text": text}, request_id=request_id, seq=seq
    )


async def send_voice_finish(self, request_id: str) -> None:
    await self._lk.send_data_event("input.voice.finish", request_id=request_id)


async def send_asr_final(self, request_id: str, text: str) -> None:
    await self._lk.send_data_event(
        "input.asr.final", data={"text": text}, request_id=request_id
    )


async def send_subtitle(
    self,
    request_id: str,
    response_id: str,
    text: str,
    seq: int,
    timestamp: int,
) -> None:
    await self._lk.send_data_event(
        "response.chunk",
        data={"text": text},
        request_id=request_id,
        response_id=response_id,
        seq=seq,
        timestamp=timestamp,
    )
```

`send_subtitle()` is the only public helper that emits `response.chunk`; it is a
caption/control-plane helper and does not invoke platform TTS.

- [ ] **Step 4: Run Session state tests**

Run: `pytest -q tests/test_session.py -k 'state or wait or scene or participant or custom'`

Expected: PASS.

- [ ] **Step 5: Commit Session lifecycle state**

```bash
git add src/liveavatar_rtc/session.py tests/test_session.py
git commit -m "feat: model rtc session readiness states"
```

---

### Task 6: Validated Audio Frames and Managed Streams

**Files:**
- Modify: `src/liveavatar_rtc/livekit_manager.py`
- Modify: `src/liveavatar_rtc/session.py`
- Test: `tests/test_livekit_manager.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `AudioFrame` and `AsyncIterable[AudioFrame]`.
- Produces: `publish_audio(frame)` and one active
  `publish_audio_stream(frames)` with validation, backpressure, and typed errors.

- [ ] **Step 1: Add failing validation, stream, and close tests**

```python
@pytest.mark.asyncio
async def test_publish_rejects_wrong_output_rate(session):
    frame = AudioFrame.from_pcm(b"\x00\x00" * 240, sample_rate=16000)
    with pytest.raises(AudioFormatError, match="24000"):
        await session.publish_audio(frame)


@pytest.mark.asyncio
async def test_publish_stream_preserves_order(session, manager):
    frames = [
        AudioFrame.from_pcm(value.to_bytes(2, "little", signed=True), 24000)
        for value in (1, 2, 3)
    ]
    await session.publish_audio_stream(async_frames(frames))
    assert manager.published_samples == [1, 2, 3]


@pytest.mark.asyncio
async def test_publish_after_close_fails(session):
    await session.close()
    with pytest.raises(SessionClosedError):
        await session.publish_audio(AudioFrame.from_pcm(b"\x00\x00", 24000))
```

- [ ] **Step 2: Run focused audio tests and observe missing validation/stream API**

Run: `pytest -q tests/test_session.py tests/test_livekit_manager.py -k 'publish or audio_format or stream'`

Expected: FAIL because frames are truncated/copied without validation and the
stream API does not exist.

- [ ] **Step 3: Implement validated capture and one managed stream**

```python
async def publish_audio_frame(self, frame: AudioFrame) -> None:
    if self._audio_source is None:
        raise RTCConnectionError("audio source is not connected")
    frame.validate_for_output(self._output_sample_rate)
    livekit_frame = rtc.AudioFrame.create(
        sample_rate=self._output_sample_rate,
        num_channels=1,
        samples_per_channel=frame.data.size,
    )
    target = np.frombuffer(livekit_frame.data.cast("b"), dtype=np.int16)
    target[:] = frame.data
    await self._audio_source.capture_frame(livekit_frame)
```

```python
async def publish_audio_stream(self, frames: AsyncIterable[AudioFrame]) -> None:
    self._ensure_open()
    if self._output_task is not None and not self._output_task.done():
        raise AudioPublishError("an audio stream is already active")

    async def publish() -> None:
        async for frame in frames:
            self._ensure_open()
            await self.publish_audio(frame)

    self._output_task = asyncio.create_task(publish())
    try:
        await self._output_task
    except asyncio.CancelledError:
        raise
    except (AudioFormatError, SessionClosedError):
        raise
    except Exception as exc:
        error = AudioPublishError("failed to publish audio stream")
        await self._events.dispatch("error", error)
        raise error from exc
    finally:
        self._output_task = None
```

- [ ] **Step 4: Run audio and Session regressions**

Run: `pytest -q tests/test_types.py tests/test_livekit_manager.py tests/test_session.py`

Expected: PASS.

- [ ] **Step 5: Commit audio stream support**

```bash
git add src/liveavatar_rtc/livekit_manager.py src/liveavatar_rtc/session.py tests/test_livekit_manager.py tests/test_session.py
git commit -m "feat: publish validated rtc audio streams"
```

---

### Task 7: Coordinated Interrupt and Idempotent Shutdown

**Files:**
- Modify: `src/liveavatar_rtc/livekit_manager.py`
- Modify: `src/liveavatar_rtc/session.py`
- Test: `tests/test_livekit_manager.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: the active Session output task and optional `request_id`.
- Produces: `interrupt(request_id: str | None = None)` and idempotent
  `Session.close()`/`LiveKitManager.disconnect()`.

- [ ] **Step 1: Add failing interrupt and repeated-close tests**

```python
@pytest.mark.asyncio
async def test_interrupt_cancels_stream_sends_control_and_emits_local_event(session, manager):
    interrupted = []
    session.on("interrupted")(lambda request_id: interrupted.append(request_id))
    stream_task = asyncio.create_task(session.publish_audio_stream(blocking_frames()))
    await asyncio.sleep(0)
    await session.interrupt("req-9")
    with pytest.raises(asyncio.CancelledError):
        await stream_task
    assert manager.last_sent_event.request_id == "req-9"
    assert manager.last_sent_event.event == "control.interrupt"
    assert interrupted == ["req-9"]


@pytest.mark.asyncio
async def test_close_is_idempotent(session, manager):
    await session.close()
    await session.close()
    assert manager.disconnect_calls == 1
```

- [ ] **Step 2: Run interrupt and cleanup tests and observe missing cancellation**

Run: `pytest -q tests/test_session.py tests/test_livekit_manager.py -k 'interrupt or close or disconnect'`

Expected: FAIL because interrupt only sends Data Channel JSON and close has no
explicit state guard.

- [ ] **Step 3: Implement coordinated interruption and ordered shutdown**

```python
async def interrupt(self, request_id: str | None = None) -> None:
    self._ensure_open()
    task = self._output_task
    if task is not None and not task.done():
        task.cancel()
    await self._lk.clear_output_queue()
    await self._lk.send_data_event("control.interrupt", request_id=request_id)
    await self._events.dispatch("interrupted", request_id)
```

Implement `clear_output_queue()` with LiveKit's public
`await self._audio_source.clear_queue()` API when the source is connected. Add
`_closing` and `_closed` guards so shutdown cancels the stream, waiters, and
remote consumers, closes the source, disconnects the room, and emits `closed`
exactly once.

- [ ] **Step 4: Run Session and manager cleanup suites**

Run: `pytest -q tests/test_session.py tests/test_livekit_manager.py`

Expected: PASS.

- [ ] **Step 5: Commit interruption and shutdown**

```bash
git add src/liveavatar_rtc/livekit_manager.py src/liveavatar_rtc/session.py tests/test_livekit_manager.py tests/test_session.py
git commit -m "feat: coordinate rtc interruption and shutdown"
```

---

### Task 8: Client Orchestration and Failure Cleanup

**Files:**
- Modify: `src/liveavatar_rtc/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `ApiClient.start_session() -> SessionInfo` and the v2
  `LiveKitManager`/`Session` constructors.
- Produces: `PlatformRTCClient(..., input_sample_rate=16000,
  output_sample_rate=24000)` and immediate `connect() -> Session`.

- [ ] **Step 1: Add failing constructor, immediate-connect, override, and cleanup tests**

```python
def test_client_has_split_sample_rates():
    signature = inspect.signature(PlatformRTCClient)
    assert signature.parameters["input_sample_rate"].default == 16000
    assert signature.parameters["output_sample_rate"].default == 24000
    assert "sample_rate" not in signature.parameters


@pytest.mark.asyncio
async def test_connect_does_not_wait_for_user(client, api, manager):
    session = await asyncio.wait_for(client.connect(), timeout=0.1)
    assert session.is_agent_connected
    manager.wait_for_user.assert_not_called()


@pytest.mark.asyncio
async def test_server_output_rate_overrides_default(client, api, manager_factory):
    api.start_session.return_value.output_sample_rate = 48000
    await client.connect()
    assert manager_factory.call_args.kwargs["output_sample_rate"] == 48000
```

- [ ] **Step 2: Run client tests and observe legacy voice/sample/wait behavior**

Run: `pytest -q tests/test_client.py`

Expected: FAIL because the client has one `sample_rate`, accepts `voice_id`, and
waits for user readiness.

- [ ] **Step 3: Implement v2 orchestration and shared cleanup**

```python
def __init__(
    self,
    api_key: str,
    avatar_id: str,
    base_url: str | None = None,
    input_sample_rate: int = 16000,
    output_sample_rate: int = 24000,
    sandbox: bool = False,
) -> None:
    self._input_sample_rate = input_sample_rate
    self._output_sample_rate = output_sample_rate
```

```python
async def connect(self) -> Session:
    if self._session is not None and not self._session.is_closed:
        return self._session
    info = await self._api.start_session(self._avatar_id)
    output_rate = info.output_sample_rate or self._output_sample_rate
    manager = LiveKitManager(
        session_id=info.session_id,
        sfu_url=info.sfu_url,
        agent_token=info.agent_token,
        user_token=info.user_token,
        input_sample_rate=self._input_sample_rate,
        output_sample_rate=output_rate,
    )
    try:
        await manager.connect()
    except Exception as exc:
        await self._cleanup_failed_connect(info.session_id, manager)
        raise RTCConnectionError(f"failed to connect RTC session {info.session_id}") from exc
    self._session = Session(manager)
    await self._events.dispatch("connection_established", self._session)
    return self._session
```

Ensure failed REST start, room connect, track publication, Session construction,
remote stop, and HTTP close paths each preserve the primary exception and perform
all remaining cleanup steps.

- [ ] **Step 4: Run client and API regressions**

Run: `pytest -q tests/test_client.py tests/test_api_client.py`

Expected: PASS.

- [ ] **Step 5: Commit client orchestration**

```bash
git add src/liveavatar_rtc/client.py tests/test_client.py
git commit -m "feat: orchestrate rtc agent v2 sessions"
```

---

### Task 9: Remove Legacy Surface and Update Documentation

**Files:**
- Modify: `src/liveavatar_rtc/session.py`
- Modify: `src/liveavatar_rtc/__init__.py`
- Modify: `tests/test_session.py`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `examples/basic_agent.py`

**Interfaces:**
- Consumes: the finalized v2 public API from Tasks 1-8.
- Produces: no platform-TTS/text exports and runnable English/Chinese examples of
  the developer-owned ASR/LLM/TTS pipeline.

- [ ] **Step 1: Add a failing public-surface test**

```python
def test_rtc_public_surface_excludes_platform_tts_and_text():
    import liveavatar_rtc

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
```

- [ ] **Step 2: Run the public-surface test and observe legacy exports**

Run: `pytest -q tests/test_session.py -k public_surface`

Expected: FAIL until every legacy export and method is removed.

- [ ] **Step 3: Remove legacy APIs and rewrite the example**

```python
client = PlatformRTCClient(
    api_key=os.environ["LIVEAVATAR_API_KEY"],
    avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
    input_sample_rate=16000,
    output_sample_rate=24000,
)

async with client as session:
    print(session.frontend_connection)
    pipeline_input: asyncio.Queue[AudioFrame] = asyncio.Queue()

    @session.on("user_audio_frame")
    async def on_user_audio(frame: AudioFrame) -> None:
        # A real application consumes this queue in its developer-owned
        # ASR/Omni pipeline, then publishes developer-owned TTS frames through
        # session.publish_audio_stream().
        await pipeline_input.put(frame)

    await session.wait_for_scene_ready(timeout=30)
    await asyncio.Event().wait()
```

Document exact lifecycle states, recommended 24 kHz mono PCM16 output, server
sample-rate override, LiveKit-owned Opus encoding, interrupt hooks, and the
platform-RTC-only scope in both README files.

- [ ] **Step 4: Run API surface and complete tests**

Run: `pytest -q`

Expected: PASS with no test referencing `voice_id`, `TTSConfig`, `INPUT_TEXT`, or
the removed platform-TTS methods.

- [ ] **Step 5: Commit documentation and legacy removal**

```bash
git add src/liveavatar_rtc/session.py src/liveavatar_rtc/__init__.py tests/test_session.py README.md README.zh.md examples/basic_agent.py
git commit -m "docs: publish rtc agent v2 usage"
```

---

### Task 10: Final Contract and Package Verification

**Files:**
- Modify: `pyproject.toml`
- Test: all `tests/`

**Interfaces:**
- Consumes: all v2 implementation tasks.
- Produces: a passing test suite and buildable breaking release package.

- [ ] **Step 1: Run the full test suite with verbose failure output**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 2: Run static import and signature checks**

Run:

```bash
python -c "import inspect, liveavatar_rtc as sdk; assert 'voice_id' not in inspect.signature(sdk.PlatformRTCClient.connect).parameters; assert 'sample_rate' not in inspect.signature(sdk.PlatformRTCClient).parameters; print(sdk.PlatformRTCClient, sdk.DataChannelEvent, sdk.AudioFormatError)"
```

Expected: prints the three public symbols and exits with status 0.

- [ ] **Step 3: Build the package**

Run: `python -m build`

Expected: creates source and wheel distributions without warnings or errors.

- [ ] **Step 4: Set the breaking release version**

Set the project version to `1.0.0` in `pyproject.toml`:

```toml
[project]
name = "liveavatar-platform-rtc"
version = "1.0.0"
```

Then rerun: `python -m build`

Expected: wheel and source distribution filenames contain `1.0.0`.

- [ ] **Step 5: Inspect the final diff and commit verification-only changes**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intentional project files and the existing
untracked `.codegraph/` and `ragflow/` paths appear.

```bash
git add pyproject.toml
git commit -m "chore: prepare rtc agent sdk v2 release"
```
