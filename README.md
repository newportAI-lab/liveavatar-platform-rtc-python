# Live Avatar Platform RTC Python SDK

[中文文档](README.zh.md)

Python agent SDK for Live Avatar **Platform RTC** mode. Join platform LiveKit rooms as `agent_{sessionId}` to drive real-time digital humans. Bring your own ASR and LLM; TTS is typically provided by the platform (or bring your own for lower latency).

The SDK runs on the developer backend, joining the platform LiveKit room as `agent_{sessionId}`. Audio flows through **RTC Tracks**, control events through the **Data Channel**.

```
                    Platform LiveKit SFU
                   ╔═══════════════╗
 user ──Audio──▶   ║               ║──Audio──▶ agent (this SDK)
 user ◀─Video+Audio ║               ║◀─Audio── agent (TTS)
 user ──Data Ch.──▶ ║               ║──Data Ch.──▶ agent
                   ╚═══════════════╝
                        │
                   renderer (platform-managed, subscribes agent Audio Track for lipsync)
```

## Installation

```bash
pip install liveavatar-platform-rtc
```

Requires Python ≥ 3.10. LiveKit access is provided by the platform.

## Quick Start

```python
from liveavatar_rtc import PlatformRTCClient, AudioFrame, USER_AUDIO_FRAME

client = PlatformRTCClient(api_key="lf_...", avatar_id="avatar-xxx")

async with client as session:
    @session.on(USER_AUDIO_FRAME)
    async def on_audio(frame: AudioFrame):
        # ASR → LLM → TTS → publish driving audio
        # await session.publish_audio(tts_output_frame)
        pass
```

## Audio Subscription

The agent automatically subscribes to **RemoteAudioTrack** streams from participants whose identity starts with `"user"` (i.e., `user_*`). All other tracks — video, agent audio, non-user participants — are ignored. Subscribed audio is resampled to the configured `sample_rate` (default 16 kHz mono int16) and dispatched as `USER_AUDIO_FRAME` events.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  PlatformRTCClient               │
│  api_key, avatar_id, base_url                    │
│  connect() → Session                             │
│  on("connection_established" / "connection_closed") │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                    Session                        │
│  Event registration on(...)                       │
│  publish_audio() / send_response_*() / interrupt() │
└──────┬──────────────────────┬───────────────────┘
       │                      │
┌──────▼────────┐   ┌─────────▼──────────────────┐
│   ApiClient   │   │     LiveKitManager          │
│               │   │                             │
│ POST /v1/     │   │  Room join/leave             │
│  session/start│   │  Audio Track subscribe (user) │
│  session/stop │   │  Audio Track publish (agent)  │
└───────────────┘   │  Data Channel send/receive    │
                    │  EventDispatcher              │
                    └──────────────────────────────┘
```

## API Reference

### PlatformRTCClient

```python
client = PlatformRTCClient(
    api_key="lf_...",                   # Platform API key
    avatar_id="avatar-xxx",             # Avatar ID
    base_url="https://facemarket.ai/vih/dispatcher",  # Optional
    sample_rate=16000,                   # Audio sample rate, default 16kHz
    sandbox=False,                       # Sandbox mode
)

# Context manager (recommended)
async with client as session:
    ...

# Or explicit
session = await client.connect()
await client.disconnect()
```

`connect()` flow: `POST /v1/session/start` → obtain token/sfuUrl → connect LiveKit → wait for user to join → return Session.

#### Connection Lifecycle

```python
@client.on("connection_established")
async def on_connected(session): ...

@client.on("connection_closed")
async def on_closed(session_id): ...
```

### Session — Event Registration

```python
@session.on(event_name)
async def handler(data): ...
```

#### Inbound Events (Data Channel, user/coordinator → agent)

| Constant | Event String | Description |
|----------|-------------|-------------|
| `INPUT_TEXT` | `"input.text"` | User text input |
| `SCENE_READY` | `"scene.ready"` | User scene is ready |
| `SESSION_STATE` | `"session.state"` | Session state change (IDLE / LISTENING / THINKING / SPEAKING) |
| `SESSION_CLOSING` | `"session.closing"` | Session is about to close |
| `IDLE_TRIGGER` | `"system.idleTrigger"` | User inactive for a while — call `send_prompt()` to proactively speak |
| `ERROR` | `"error"` | Platform/coordinator error |

#### Inbound Events (RTC Track, SDK-level)

| Constant | Event String | Description |
|----------|-------------|-------------|
| `USER_AUDIO_FRAME` | `"user_audio_frame"` | User audio PCM frame (resampled to configured sample_rate) |
| `USER_AUDIO_TRACK_SUBSCRIBED` | `"user_audio_track_subscribed"` | User Audio Track ready |
| `USER_JOINED` | `"user_joined"` | User joined the room |
| `DISCONNECTED` | `"disconnected"` | LiveKit connection lost |

### Session — TTS Output

#### Developer-provided TTS (publish Audio Track)

```python
# Publish PCM frame to agent Audio Track; renderer auto-subscribes for lipsync
await session.publish_audio(frame: AudioFrame)
```

#### Platform-provided TTS (Data Channel text stream)

```python
request_id = await session.send_response_start(config: TTSConfig | None) → str
await session.send_response_chunk(request_id, text)
await session.send_response_done(request_id)
await session.send_response_cancel(request_id)          # Cancel in-progress response
```

#### Subtitles

```python
# Send caption text to frontend (uses response.chunk, shown as subtitle)
await session.send_subtitle(request_id, text)
```

### Session — Developer TTS Audio Lifecycle

When using developer TTS via `publish_audio()`, bracket the audio stream with lifecycle events so the coordinator can drive its state machine:

```python
# Normal conversation reply — bracket publish_audio()
req_id = await session.send_response_audio_start()
# ... stream TTS PCM via await session.publish_audio() ...
await session.send_response_audio_finish(req_id)

# Proactive / idle-prompt speech — bracket publish_audio()
req_id = await session.send_response_audio_prompt_start()
# ... stream TTS PCM via await session.publish_audio() ...
await session.send_response_audio_prompt_finish(req_id)
```

The `promptStart`/`promptFinish` variant tells the coordinator this is an unsolicited prompt (triggered by `system.idleTrigger`), not a user-requested reply.

### Session — Developer ASR

```python
await session.send_asr_partial(text)   # Interim result → frontend captions
await session.send_asr_final(text)     # Final result → frontend + coordinator
```

### Session — Developer VAD (required when using developer ASR)

When you provide your own ASR, you **must** send VAD boundary events so the coordinator can drive its state machine:

```python
# ── Call these around your ASR pipeline ──
await session.send_voice_start()       # User started speaking (VAD start)
# ... ASR processing ...
await session.send_voice_finish()      # User stopped speaking (VAD end)
```

Without these events the coordinator cannot transition between LISTENING / THINKING / SPEAKING states correctly.

### Session — Control

```python
await session.interrupt()                      # Interrupt current speech
await session.send_prompt("Hey, how are you?") # Trigger proactive speech
```

### Session — Error Reporting

```python
await session.send_error("E001", "TTS service unavailable")
```

### Session — Lifecycle

```python
await session.wait_until_ready(timeout=30.0)   # Wait for user to join
await session.close()                            # Leave room, release resources
```

## Data Types

### AudioFrame

```python
@dataclass
class AudioFrame:
    data: np.ndarray      # PCM int16 samples
    sample_rate: int      # Hz
    num_channels: int     # 1 = mono
    timestamp: int = 0    # LiveKit timestamp (μs)

    # Factory methods
    AudioFrame.from_pcm(pcm: bytes, sample_rate: int, num_channels: int = 1) → AudioFrame
    AudioFrame.from_ndarray(data: np.ndarray, sample_rate: int, timestamp: int = 0) → AudioFrame

    # Serialization
    frame.to_pcm_bytes() → bytes
```

### AudioTrackInfo

```python
@dataclass
class AudioTrackInfo:
    sample_rate: int
    num_channels: int
    participant_identity: str   # e.g. "user_alice"
    track_sid: str = ""
```

### TTSConfig

```python
@dataclass
class TTSConfig:
    speed: float | None = None   # e.g. 1.0
    volume: float | None = None  # e.g. 1.0
    mood: str | None = None      # e.g. "cheerful"
```

## Integration Examples

### Voice Conversation (developer ASR + LLM + TTS)

```python
import asyncio
from liveavatar_rtc import (
    PlatformRTCClient, AudioFrame, TTSConfig,
    USER_AUDIO_FRAME, INPUT_TEXT, SESSION_STATE,
    IDLE_TRIGGER, DISCONNECTED, ERROR,
)

async def main():
    client = PlatformRTCClient(
        api_key="lf_...",
        avatar_id="avatar-xxx",
        sample_rate=16000,
    )

    async with client as session:

        @session.on(USER_AUDIO_FRAME)
        async def on_audio(frame: AudioFrame):
            # 1. ASR: frame.data (int16 PCM) → text
            text = await my_asr(frame.data)
            await session.send_voice_start()
            await session.send_asr_partial(text)
            await session.send_asr_final(text)
            await session.send_voice_finish()

            # 2. LLM → reply
            reply = await my_llm(text)

            # 3. TTS → PCM → publish, wrapped in audio lifecycle
            req_id = await session.send_response_audio_start()
            pcm = await my_tts(reply)
            await session.publish_audio(AudioFrame.from_pcm(pcm, sample_rate=24000))
            await session.send_response_audio_finish(req_id)

        @session.on(INPUT_TEXT)
        async def on_text(data: dict):
            reply = await my_llm(data.get("text", ""))
            # Use platform TTS
            req_id = await session.send_response_start(TTSConfig(speed=1.0))
            await session.send_response_chunk(req_id, reply)
            await session.send_response_done(req_id)

        @session.on(IDLE_TRIGGER)
        async def on_idle(_data):
            prompt = await my_idle_prompt()
            await session.send_prompt(prompt)

        @session.on(SESSION_STATE)
        async def on_state(data: dict):
            print(f"State: {data.get('state')}")

        @session.on(ERROR)
        async def on_error(data: dict):
            print(f"Error: {data}")

        await session.wait_until_ready()
        print(f"Agent ready, session={session.session_id}")

        disconnect_event = asyncio.Event()

        @session.on(DISCONNECTED)
        async def wait_disconnect(reason):
            print(f"Disconnected: {reason}")
            disconnect_event.set()

        await disconnect_event.wait()

asyncio.run(main())
```

### Platform TTS Mode (developer returns text only)

```python
async with client as session:

    @session.on(USER_AUDIO_FRAME)
    async def on_audio(frame: AudioFrame):
        text = await my_asr(frame.data)
        reply = await my_llm(text)

        # TTS handled by platform; developer returns text only
        req_id = await session.send_response_start(TTSConfig(speed=1.2, mood="cheerful"))
        await session.send_response_chunk(req_id, reply)
        await session.send_response_done(req_id)

    await session.wait_until_ready()
    await asyncio.Event().wait()  # run forever
```

## Differences from the WebSocket SDK

This SDK shares the same event naming convention as [`liveavatar-channel-python`](https://github.com/newportAI-lab/liveavatar-channel-python) (WebSocket protocol). Business logic is largely reusable across modes.

| Aspect | WebSocket SDK | This SDK (Platform RTC) |
|--------|--------------|------------------------|
| Transport | WebSocket binary + JSON | LiveKit RTC Track + Data Channel |
| Audio receive | Binary frame (byte stream) | Audio Track subscription (PCM frames) |
| Audio send | Binary frame | Audio Track publication |
| Identity | No room concept | `agent_{sessionId}` |
