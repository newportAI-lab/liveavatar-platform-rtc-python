# RTC Agent SDK v2 Design

## Summary

This document defines a breaking upgrade of the Python SDK for the Live Avatar
**RTC Agent - Platform RTC** mode. The SDK connects a developer-owned Agent
pipeline to the platform-owned LiveKit room, subscribes to user audio, and
publishes developer-generated audio that drives the Avatar renderer.

The upgrade does not add WebSocket Agent behavior. It does not include BYO RTC,
multiple users or user tracks, or multiple Avatars/Agents in one room.

## Goals

- Make `mode="rtcAgent"` explicit when starting a session.
- Return after the Agent is connected and its audio track is published, without
  waiting for the user to join.
- Expose frontend connection information without exposing Agent credentials.
- Model Agent connection, user presence, user audio, scene readiness, and room
  lifecycle as separate states.
- Separate inbound and outbound audio sample rates.
- Provide validated frame and stream publishing with cancellation and backpressure.
- Preserve complete Data Channel message envelopes and support typed and custom events.
- Surface LiveKit participant, track, reconnection, and connection-quality events.
- Provide structured errors and deterministic, idempotent cleanup.
- Remove platform-TTS and platform-text-input APIs that do not belong to RTC Agent.

## Non-goals

- WebSocket Agent connection, handshake, binary framing, or reconnect behavior.
- RTC Agent - BYO RTC.
- Multiple users, multiple simultaneous user audio tracks, multiple Agents, or
  multiple Avatar renderers in the same room.
- SDK-owned ASR, LLM, TTS, VAD, or conversation orchestration.
- SDK-owned PCM resampling or Opus encoding.
- Backward compatibility with the current public API.

## Architecture

The current three-layer structure is retained and its responsibilities are made
explicit.

### `PlatformRTCClient`

- Owns the HTTP client and REST session lifecycle.
- Calls `/v1/session/start` with `avatarId` and `mode: "rtcAgent"`.
- Parses the platform RTC connection result.
- Creates and connects `LiveKitManager`.
- Returns a `Session` as soon as the Agent has joined and published its local
  audio track.
- Stops the remote session and closes HTTP resources during disconnect.

### `Session`

- Is the primary public developer API.
- Exposes frontend-safe connection information.
- Exposes current RTC and scene state.
- Provides event registration and state waiters.
- Publishes individual audio frames and asynchronous audio streams.
- Coordinates local audio-stream cancellation and platform interruption.
- Sends typed control events and arbitrary forward-compatible Data Channel events.

### `LiveKitManager`

- Owns the LiveKit room, local `AudioSource`, and local Agent audio track.
- Observes participants and remote audio tracks.
- Converts the selected user audio track to mono PCM at `input_sample_rate`.
- Publishes Agent PCM through an `AudioSource` configured at
  `output_sample_rate`.
- Parses and sends Data Channel events on the `liveavatar` topic.
- Surfaces reconnect, reconnected, disconnected, and connection-quality events.
- Cancels track-consumer tasks and closes media resources deterministically.

No generic transport abstraction is introduced because this SDK supports only
the platform-owned LiveKit topology.

## Session Start and Public Models

The REST request is:

```json
{
  "avatarId": "avatar-id",
  "mode": "rtcAgent"
}
```

`voiceId` is removed from all public APIs and request models. RTC Agent TTS is
always developer-owned.

The response model continues to parse `sessionId`, `userToken`, `agentToken`,
and `sfuUrl`. It may also parse a platform-provided output sample rate when the
service exposes one.

The Agent token remains internal. Frontend-safe values are exposed as a separate
immutable model:

```python
@dataclass(frozen=True)
class FrontendConnection:
    user_token: str
    sfu_url: str
```

The public flow is:

```python
client = PlatformRTCClient(
    api_key=api_key,
    avatar_id=avatar_id,
    input_sample_rate=16000,
    output_sample_rate=24000,
)

session = await client.connect()
frontend = session.frontend_connection

await session.wait_for_user(timeout=30)
await session.wait_for_scene_ready(timeout=30)
```

`connect()` completes after the Agent room connection and local audio-track
publication. User presence and scene readiness never gate `connect()`.

## Session State and Waiters

`Session` exposes at least these states:

```python
session.is_agent_connected
session.is_user_joined
session.is_scene_ready
session.is_user_audio_subscribed
session.is_closing
session.is_closed
```

It provides explicit waiters for states that callers commonly coordinate around:

```python
await session.wait_for_user(timeout=30)
await session.wait_for_user_audio(timeout=30)
await session.wait_for_scene_ready(timeout=30)
```

Waiter rules:

- Return immediately when the state is already satisfied.
- Raise a structured timeout error when the deadline expires.
- Fail immediately with `SessionClosedError` when the session closes.
- Never leave tasks suspended after close.
- Clear participant and track state when the relevant participant or track leaves.
- Rebuild participant and track state from LiveKit events following reconnection.

`scene.ready` is idempotent. The first valid event sets the state and resolves
waiters. Duplicate events do not create duplicate state transitions.

## Participant and Track Semantics

The SDK recognizes the documented logical room roles:

- `user...`
- `coordinator_{sessionId}`
- `renderer_{sessionId}`
- local `agent_{sessionId}`

User identity matching intentionally remains permissive with
`identity.startswith("user")` until the platform contract is finalized. The
predicate is centralized in one helper so the rule can change without touching
track and lifecycle handlers.

The SDK supports one logical user audio track. It should:

- Accept only remote audio tracks from a recognized user participant.
- Prefer or require a microphone-source publication when LiveKit exposes source
  metadata.
- Replace the tracked user audio stream deterministically when the same user
  republishes a track.
- Cancel the previous consumer before starting the replacement consumer.
- Surface subscribe, unsubscribe, mute, and unmute transitions when supported by
  the installed LiveKit SDK.

The following participant and media events are surfaced:

- `user_joined`, `user_left`
- `user_audio_subscribed`, `user_audio_unsubscribed`
- `coordinator_joined`, `coordinator_left`
- `renderer_joined`, `renderer_left`
- `scene_ready`
- `session_state`, `session_closing`

## Audio Configuration and Processing

Inbound and outbound audio have independent settings:

```python
input_sample_rate: int = 16000
output_sample_rate: int = 24000
```

### User audio input

`input_sample_rate` configures `rtc.AudioStream`. LiveKit produces mono PCM at
that sample rate for the developer's ASR, Omni model, or Voice Agent pipeline.
The user's original microphone format does not need to match it.

### Agent audio output

`output_sample_rate` configures the local `rtc.AudioSource`. The recommended
default is 24 kHz, mono, PCM16 (two bytes per sample). If `/session/start`
returns the Avatar's configured driving sample rate, the server value overrides
the local default for that session.

LiveKit is responsible for RTC media processing and Opus encoding. The SDK does
not implement an Opus packet format and does not silently resample developer
output.

Before capture, every output frame is validated:

- `num_channels == 1`
- PCM data is signed 16-bit samples
- `frame.sample_rate == session.output_sample_rate`
- the sample count and payload length are internally consistent

Invalid frames raise `AudioFormatError` before reaching LiveKit.

## Audio Publishing and Interruption

The SDK supports individual frames and asynchronous streams:

```python
await session.publish_audio(frame)
await session.publish_audio_stream(frames)
```

`publish_audio_stream()`:

- Accepts `AsyncIterable[AudioFrame]`.
- Preserves frame order.
- Awaits `AudioSource.capture_frame()` to honor LiveKit backpressure.
- Stops on task cancellation, session close, format error, or capture error.
- Allows only one SDK-managed output stream at a time.
- Emits a structured error event on non-cancellation failures.

`interrupt(request_id=None)` performs four coordinated actions:

1. Cancels the currently managed `publish_audio_stream()` task, if any.
2. Clears the local LiveKit audio queue when the installed SDK exposes a safe
   queue-clear API; otherwise it stops future capture without relying on private APIs.
3. Sends `control.interrupt` on the `liveavatar` Data Channel topic.
4. Emits a local `interrupted` event so the developer can cancel its LLM/TTS task.

The SDK does not own or cancel arbitrary developer pipeline tasks.

## Data Channel Protocol

Inbound messages retain their complete envelope:

```python
@dataclass(frozen=True)
class DataChannelEvent:
    event: str
    data: dict
    request_id: str | None = None
    response_id: str | None = None
    seq: int | None = None
    timestamp: int | None = None
    participant_identity: str | None = None
    topic: str | None = None
```

Inbound rules:

- Ignore packets whose topic is not `liveavatar`.
- Decode UTF-8 JSON objects only.
- Reject malformed known events with `DataChannelProtocolError` and an error event.
- Keep sender identity validation permissive for this version.
- Update Session state for known lifecycle events.
- Dispatch unknown valid events as `custom_event` without discarding fields.

Typed public methods construct supported control and observability events. A
general method preserves forward compatibility:

```python
await session.send_custom_event(
    event="vendor.action",
    data={...},
    request_id=None,
    response_id=None,
    seq=None,
    timestamp=None,
)
```

## Removed RTC-Inappropriate APIs

Because RTC Agent owns its TTS and platform-side text input is unsupported, the
breaking release removes:

- `voiceId` and the `voice_id` parameter
- `TTSConfig`
- `INPUT_TEXT`
- `send_response_start()`
- `send_response_chunk()`
- `send_response_done()`
- `send_prompt(text)`
- platform-TTS prompt-audio lifecycle methods

It retains audio publication, interruption, speech-boundary events, ASR result
events, subtitle/status events, error events, and custom Data Channel events.

## LiveKit Connection Events

The SDK surfaces, rather than merely logs:

- `reconnecting`
- `reconnected`
- `disconnected`
- `connection_quality_changed`

LiveKit remains responsible for transport reconnection. The SDK does not add a
second retry loop. During reconnection the `Session` object remains valid; room,
participant, and track events rebuild observable state.

## Error Model

The public exception hierarchy is:

```text
RTCSDKError
├── APIError
├── SessionStartError
├── RTCConnectionError
├── SessionClosedError
├── SessionWaitTimeoutError
├── AudioFormatError
├── AudioPublishError
└── DataChannelProtocolError
```

Wrapped errors preserve the original exception as `__cause__`. Error messages
identify the failed lifecycle stage and session ID when available. Protocol and
media errors are also emitted through the Session event dispatcher so long-lived
applications can observe failures without relying only on logs.

## Shutdown and Failure Cleanup

`disconnect()` and `Session.close()` are idempotent. Connection failure and normal
shutdown use the same ordered cleanup path:

1. Mark the Session as closing and reject new work.
2. Cancel the managed output stream and all state waiters.
3. Cancel remote audio-consumer tasks.
4. Close the local AudioSource.
5. Disconnect the LiveKit room.
6. Call `/session/stop` when a remote session was created.
7. Close the HTTP client.
8. Mark the Session closed and emit the final event.

A failure in one cleanup step does not skip later steps. The primary failure is
raised; cleanup failures are logged and emitted as secondary errors.

## Testing Strategy

Tests retain the repository's pytest and mocked-LiveKit style. Coverage includes:

- Session start always sends `mode="rtcAgent"` and never sends `voiceId`.
- Agent connect returns after local audio publication without waiting for a user.
- Frontend connection data excludes Agent credentials.
- User, coordinator, and renderer participant transitions.
- User-track subscribe, replacement, unsubscribe, mute, and unmute behavior.
- `scene.ready` state, duplicates, immediate waits, successful waits, timeout,
  and close cancellation.
- Independent input/output sample rates and server-side output override.
- PCM16, mono, sample-rate, sample-count, and closed-session validation.
- Stream ordering, backpressure, cancellation, failure, and close behavior.
- Interrupt cancellation, local event, and Data Channel message.
- Full Data Channel envelope preservation, topic filtering, malformed messages,
  typed events, and custom events.
- Reconnecting, reconnected, disconnected, and connection-quality propagation.
- Every connection failure stage performs complete cleanup.
- Repeated close/disconnect calls are harmless.
- Removed APIs and exports are absent.

The example and README are updated to demonstrate the RTC Agent flow:

```text
user audio -> developer ASR/Omni -> developer LLM -> developer TTS
           -> Session audio publication -> Avatar renderer
```

## Acceptance Criteria

- The complete test suite passes after invalid legacy tests are replaced.
- The public API contains no platform-TTS or platform-text-input entry points.
- `connect()` cannot deadlock frontend token delivery by waiting for a user.
- Scene readiness and participant/media states are independently observable.
- Invalid developer audio fails before capture with a typed error.
- A managed output stream can be interrupted and cannot continue publishing after
  close.
- Valid `liveavatar` Data Channel messages reach callers without losing envelope
  fields.
- LiveKit reconnect and room lifecycle changes are observable without adding a
  competing retry loop.
- Documentation clearly states the platform-RTC-only scope and developer-owned
  Agent pipeline.
