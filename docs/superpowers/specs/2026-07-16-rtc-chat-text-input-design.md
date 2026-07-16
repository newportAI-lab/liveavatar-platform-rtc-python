# RTC Chat Text Input Design

## Context

RTC mode digital human playback still consumes audio from the agent. Users, however, may input either speech or text in the chat demo.

The current rtc-chat demo already has most of this path:

- The browser sends text with `client.sendTextQuestion(text)`.
- The backend receives RTC custom event `input.text`.
- `ChatPipeline.on_text_input()` runs the same LLM -> TTS -> RTC audio publication response path as voice turns.

## Goals

- Treat text input as a user turn handled by the agent.
- Keep platform-side digital human input audio-only.
- Reuse the existing LLM -> TTS -> `publish_audio_stream` pipeline for text turns.
- Keep text turns gated until the pipeline is ready.
- Preserve interrupt behavior: a new text turn cancels the previous active output.
- Add tests and documentation that make the text-input behavior explicit.

## Non-Goals

- Do not change UI copy or input placeholder text.
- Do not add a platform-side text-driving protocol.
- Do not change the RTC SDK browser API.
- Do not change ASR behavior for voice turns.

## Design

Text and voice input share the same response pipeline after user input is normalized:

```text
Voice: mic audio -> ASR final -> on_asr_final() -> LLM -> TTS -> RTC audio
Text:  input.text event -> on_text_input() -> LLM -> TTS -> RTC audio
```

For text input, the agent skips ASR protocol events. It may still send subtitles and TTS audio for the response exactly like a voice turn. The digital human platform receives only published TTS audio.

`on_text_input()` remains behind `_ready_event`, so text submitted before readiness waits until the scene gate, ASR connection, and TTS connection have joined. `scene.ready` means the avatar video scene is ready to present output; it is not an ASR or TTS resource dependency. If readiness fails, the text turn is ignored because `_ready` stays false or the pipeline is closed.

## Testing

Add focused coverage that verifies:

- A text custom event runs LLM -> TTS -> `publish_audio_stream`.
- Text input does not emit voice/ASR input protocol events.
- A new text turn interrupts the current output before starting a new response.

## Documentation

Update rtc-chat documentation to state:

- Users can type or speak.
- Text input is handled by the agent and converted to TTS audio.
- The RTC platform still receives audio output only.
