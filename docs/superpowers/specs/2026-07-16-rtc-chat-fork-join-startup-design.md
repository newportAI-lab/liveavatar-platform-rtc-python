# RTC Chat Fork/Join Startup Design

## Context

The rtc-chat demo currently starts external and RTC dependencies mostly in sequence. The observed startup flow is:

1. Connect to the LiveAvatar RTC runtime.
2. Wait for user join.
3. Wait for user audio subscription.
4. Wait for `scene.ready`.
5. Connect DashScope ASR.
6. Mark the chat pipeline ready.

This makes external ASR connection latency part of the user-visible ready path. It also means a transient 5 second DashScope ASR WebSocket timeout tears down an otherwise ready RTC session.

The user confirmed two requirements:

- ASR may connect before the user joins and before `scene.ready`.
- TTS should also keep a long-lived WebSocket connection created during startup.

## Goals

- Reduce time from RTC session creation to chat readiness by connecting independent dependencies concurrently.
- Keep current RTC-side scene gate ordering for user, audio, and scene events.
- Keep `_ready = True` gated until the scene gate, ASR connection, and TTS connection have all completed.
- Preserve current cleanup behavior: if one startup branch fails, cancel/close the other initialized resources.
- Keep audio and text inputs gated until all branches have joined.
- Do not introduce BYO RTC, multi-user, multi-track, or multi-avatar behavior.

## Non-Goals

- Do not change platform protocol semantics.
- Do not change ASR, LLM, or TTS vendors.
- Do not pre-create LLM responses.
- Do not add LLM warmup in this iteration.
- Do not retry ASR or TTS in this design. Retry can be added separately after the parallel startup behavior is stable.

## Proposed Architecture

`ChatPipeline.start()` registers all RTC event handlers first, then forks three startup branches. `scene.ready` is a video-scene signal: it means the avatar rendering scene is ready to present output, not that ASR or TTS resources are ready.

- `scene_gate`: wait for user join, user audio subscription, and `scene.ready` in the existing order.
- `asr_connection`: connect and configure the DashScope ASR WebSocket.
- `tts_connection`: connect and configure a DashScope TTS WebSocket for reuse by future response generations.

The pipeline joins these branches with `asyncio.gather()`. It sets `_ready = True` only after all three have completed. If any branch fails, the pipeline cancels unfinished startup tasks, records the readiness error, sets `_ready_event`, and lets Runtime perform the existing failed-readiness cleanup.

## TTS Lifecycle Change

Today `QwenTts.start()` creates a new provider, connects it, configures the session, and starts one response generation. Long-lived TTS requires separating connection readiness from response generation:

- Add `QwenTts.connect()` for startup-time provider creation, WebSocket connection, and session configuration.
- Keep `QwenTts.start()` as the per-response generation boundary.
- Make `start()` reuse an already connected provider instead of closing it and creating a new one.
- Make `cancel()` clear appended text on the connected provider and end only the current generation.
- Make `close()` close the long-lived provider.

The connected provider remains associated with the `QwenTts` instance. Generation-specific callbacks must still ignore late events from older generations, preserving the current protection against stale audio.

## Data Flow

```text
Runtime.start()
  -> client.connect()
  -> create asr/llm/tts/pipeline
  -> pipeline.start()
       -> register RTC handlers
       -> fork scene_gate, asr_connection, tts_connection
       -> join all
       -> ready = true
```

During forked startup, incoming audio and text remain gated by `_ready`, so no audio is fed to ASR and no text turn is processed before ASR and TTS are both available.

## Error Handling

- If `asr_ready` fails, cancel the RTC and TTS startup branches and let Runtime cleanup close the session.
- If `tts_ready` fails, cancel the RTC and ASR startup branches and let Runtime cleanup close the session.
- If `scene_gate` fails or times out, cancel ASR/TTS startup branches and let Runtime cleanup close the session.
- `close()` remains idempotent and must clean up partially connected providers.

## Testing

Add focused tests in the rtc-chat demo:

- `ChatPipeline.start()` starts ASR and TTS connection concurrently with the scene gate.
- `_ready` is not set until the scene gate, ASR connection, and TTS connection have all completed.
- Audio frames are not forwarded before the join completes.
- A startup failure in one branch cancels pending branches and is surfaced to Runtime cleanup.
- `QwenTts.connect()` connects/configures once during startup.
- `QwenTts.start()` reuses the connected provider across generations.
- `QwenTts.close()` closes a connected but inactive provider.

## Acceptance Criteria

- Startup logs show separate scene gate, ASR connection, and TTS connection durations.
- A slow ASR or TTS connection can overlap with user/audio/scene gate waiting.
- Existing chat behavior, interruption behavior, and TTS cancellation tests continue to pass.
- The full rtc-chat test suite passes.
