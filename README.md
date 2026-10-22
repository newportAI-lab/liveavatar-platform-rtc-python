# Live Avatar Platform RTC Python SDK

[中文文档](README.zh.md)

Backend agent SDK for Live Avatar **Platform RTC** mode. Your application owns
ASR, LLM, and TTS. The SDK connects that pipeline to the platform LiveKit room:
user audio arrives as PCM frames, and your TTS PCM frames drive avatar speech.
There is no platform-TTS or text-input compatibility API in this package.

**Version 1.0.3**

## Install

```bash
pip install liveavatar-platform-rtc
```

Python 3.10 or newer is required.

## Development install

```bash
pip install -e ".[dev]"
```

## Minimal agent

```python
import asyncio
import os
from liveavatar_rtc import AudioFrame, PlatformRTCClient

client = PlatformRTCClient(
    api_key=os.environ["LIVEAVATAR_API_KEY"],
    avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
    input_sample_rate=16000,
    output_sample_rate=24000,
)

async with client as session:
    print(session.frontend_connection)  # distribute to your frontend
    pipeline_input: asyncio.Queue[AudioFrame] = asyncio.Queue()

    @session.on("user_audio_frame")
    async def on_user_audio(frame: AudioFrame) -> None:
        # Feed your ASR/Omni model, then publish your own TTS frames.
        await pipeline_input.put(frame)

    await session.wait_for_user(timeout=30)
    await session.wait_for_scene_ready(timeout=30)
    await asyncio.Event().wait()
```

See [`examples/basic_agent.py`](examples/basic_agent.py) for a syntactically
runnable, provider-free pipeline skeleton. It connects and consumes user audio,
but intentionally produces no avatar speech until real developer ASR, LLM, and
TTS are integrated; it prints this warning at startup.

For the full Platform RTC protocol model, see [`PROTOCOL.md`](PROTOCOL.md).

## Connection and readiness stages

1. `await client.connect()` (or enter the context manager) starts the platform
   session and connects the backend agent to LiveKit.
2. Send `session.frontend_connection` to the frontend. It contains only the
   user's `user_token` and `sfu_url`; never send the API key or agent token.
3. `await session.wait_for_user()` waits for that frontend user to join.
4. `await session.wait_for_scene_ready()` waits for the `scene.ready` event (sent by the platform through the
   renderer). Start avatar output after this stage.

The observable flags are `is_agent_connected`, `is_user_joined`,
`is_user_audio_subscribed`, `is_scene_ready`, `is_closing`, and `is_closed`.
Wait methods raise `SessionWaitTimeoutError` on timeout and
`SessionClosedError` if the session closes first.

## Developer-owned audio pipeline

The SDK emits `user_audio_frame` with mono PCM16 resampled to
`input_sample_rate` (16 kHz by default), ready for developer-owned ASR or an
omni model. Your LLM and TTS remain entirely in your backend.

Publish TTS with `await session.publish_audio(frame)` or stream an async
iterable with `await session.publish_audio_stream(frames)`. Output must be mono
PCM16 at the negotiated output rate. The recommended and client default rate is
24 kHz. A session-start response may override `output_sample_rate`; the SDK
validates against that server-selected rate. LiveKit, not application code,
owns real-time playout buffering and Opus encoding.

```python
async def tts_frames():
    async for pcm in my_streaming_tts():
        yield AudioFrame.from_pcm(pcm, sample_rate=24000)

await session.publish_audio_stream(tts_frames())
```

External audio does not use `publish_audio`. That track is voice and drives lip sync.

```python
client = PlatformRTCClient(..., external_audio_config={"sampleRate": 48000, "channels": 2})
session = await client.connect()
await session.publish_external_audio(pcm)
await session.interrupt(interrupt_scope="BGM_ONLY")
await session.interrupt(interrupt_scope="VOICE_AND_ACCOMPANIMENT")
```

`PlatformRTCClient` adds the optional parameter `external_audio_config`. Omit it to follow the session voice format. A non-zero `sampleRate` must be 16000, 24000, 44100, or 48000. `channels` is 1 or 2. It is sent as `externalAudioConfig` on session start.

`publish_external_audio(pcm)` sends accompaniment. `pcm` is 16-bit little-endian PCM and is played without driving lip sync. Do not use `publish_audio` for this audio. Its sample rate and channel count must match `external_audio_config` when that parameter is set. When it is not set, they must match the TTS audio format used for this session.

`send_external_playback(request_id, response_id, frames)` plays developer PCM as the voice turn while platform TTS is enabled. The control events are `response.audio.start` and `response.audio.finish` with `data.purpose=external`. The PCM stays raw LiveKit audio and is not wrapped in the WebSocket frame header. The SDK does not resample. This requires a Dispatcher that accepts `purpose=external` and forwards the agent audio track as raw PCM.

The PCM is base64-encoded inside a data-channel message, so keep the PCM itself at or below 48000 bytes. The encoded message then stays under the 65536-byte limit that closes an oversized frame. Send each later packet before the audio already queued has finished playing. For example, do not wait a full 200 ms before sending the next 200 ms packet. Make the first packet longer than the later packets, while still staying under the size limit, so playback has audio waiting when it starts.

`interrupt` adds the string parameter `interrupt_scope`.

| Value | Effect |
|---|---|
| omitted, empty, or `VOICE_ONLY` | Stop voice playback, cancel the local voice stream, clear queued voice audio, and emit `interrupted` |
| `BGM_ONLY` | Clear queued external audio only. The local voice stream keeps running |
| `VOICE_AND_ACCOMPANIMENT` | Stop voice playback and clear queued external audio. The local voice stream is also cancelled |

The value is sent as `data.interruptScope` on `control.interrupt`. Audio that belongs to the base video is not cleared.

## Events and protocol hooks

Register handlers with `@session.on(event_name)`. Common SDK events are
`USER_AUDIO_FRAME`, `USER_JOINED`, `USER_LEFT`, `SCENE_READY`,
`SCENE_RESOURCE_TRANSITION`, `SESSION_STATE`, `SESSION_CLOSING`, `DISCONNECTED`, `ERROR`, and
`CUSTOM_EVENT`. Unknown data-channel envelopes are delivered as
`CUSTOM_EVENT` without discarding their metadata.

RTC Agent protocol packets are reliable LiveKit Data Channel messages without a
required topic. The SDK dispatches by the JSON `event` field and does not filter
incoming packets by topic. `DataChannelEvent.topic` is retained only for
diagnostics when a participant supplies one.

The platform sends `SCENE_RESOURCE_TRANSITION` when the renderer has finished
the current video and is about to switch to the next configured video resource.
This is a one-way notification; the handler return value does not acknowledge,
cancel, or delay the renderer switch.

```python
from liveavatar_rtc import DataChannelEvent, SCENE_RESOURCE_TRANSITION

@session.on(SCENE_RESOURCE_TRANSITION)
async def on_resource_transition(event: DataChannelEvent) -> None:
    previous_id = event.data["previousResourceId"]
    next_id = event.data["nextResourceId"]
    message = event.data.get("message")
```

`previousResourceId` and `nextResourceId` are required stable business resource
IDs, not URLs, file paths, or display names. `message` is optional
human-readable context for logs or diagnostics; do not branch business logic on
it. `session_id`, `request_id`, `timestamp`, participant identity, and topic are
envelope metadata on `DataChannelEvent`, not fields inside `data`. There is no
`streamId` field because the active RTC session already scopes the stream.

Developer ASR/VAD and application-specific observability integrations can use:

```python
await session.send_voice_start(request_id)
await session.send_asr_partial(request_id, text, seq)
await session.send_voice_finish(request_id)
await session.send_asr_final(request_id, text)
await session.send_custom_event("vendor.event", {"value": 1})
```

The RTC SDK does not provide `response.chunk` / `response.done` helpers. Avatar
speech is driven by the developer-published LiveKit audio track, not by platform
text TTS. If your application needs subtitles or diagnostics, send an explicit
custom event that your own frontend or backend understands.

Close with `await session.close()` or leave the client context manager. The
context manager also stops the remote platform session.

## Scope

This package is only for Platform RTC agent backends. It transports PCM audio
over LiveKit audio tracks and structured control events over the LiveKit data
channel. Its public surface contains only the v2 Platform RTC agent API, without
legacy compatibility aliases.
