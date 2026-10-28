# Changelog

**English** | [中文](./CHANGELOG.zh-CN.md)

Notable changes to this SDK are documented here. The date is the release day.

## [1.0.3] - 2026-10-22

1. Added: `send_external_playback(request_id, response_id, frames)` plays developer PCM as the voice turn while platform TTS is enabled. It sends `response.audio.start` and `response.audio.finish` with `data.purpose=external`. The PCM is published as raw LiveKit audio and is not given a WebSocket frame header. The SDK does not resample. This is not `publish_external_audio`, which remains accompaniment and does not replace speech. If publishing fails after start, `response.audio.finish` is still sent. The platform Dispatcher must accept `purpose=external` and forward the agent audio track as raw PCM.

## [1.0.2] - 2026-10-15

1. Added: `PlatformRTCClient` adds the optional parameter `external_audio_config`. Omit it to follow the session voice format. A non-zero `sampleRate` must be 16000, 24000, 44100, or 48000. `channels` is 1 or 2. On session start it is sent as `externalAudioConfig`.
2. Added: `publish_external_audio(pcm)` is a new method. `pcm` is 16-bit little-endian PCM and does not drive lip sync. Do not use `publish_audio` or `publish_audio_stream`. It is sent as the data-channel event `external.audio.chunk`. Its sample rate and channel count must match `external_audio_config` when set, otherwise the session TTS format. Keep the PCM at or below 48000 bytes so the base64 data-channel message stays under 65536 bytes. Send later packets before the queued audio finishes, and make the first packet longer than the later ones without exceeding that limit.
3. Added: `interrupt` adds the string parameter `interrupt_scope`. An omitted value, an empty value, and `VOICE_ONLY` stop voice playback and cancel the local voice stream. `BGM_ONLY` clears queued external audio only and leaves the local voice stream running. `VOICE_AND_ACCOMPANIMENT` stops voice playback, clears queued external audio, and cancels the local voice stream. Surrounding spaces are removed. Any other value is rejected before sending. The value is sent as `data.interruptScope` on `control.interrupt`. Base-video audio is not cleared.
4. Changed: `scene.ready` is sent by the platform through the renderer. The room no longer has a coordinator participant.
5. Changed: session start fields `onceVideoIds` and `loopVideoIds`, and `scene.switchVideo` fields `onceVideos`, `loopVideos`, and `videoChoreographyGroups`, used to accept only resource IDs. Each item may now also be an alias of that avatar's base video. An alias is 3 to 32 characters, starts with a letter, uses only lowercase letters, digits, and underscores, and does not end with an underscore. The SDK passes the string through. The platform replaces an alias with its resource ID before playback.

## [1.0.1] - 2026-08-06

### Added

- Resource transition messages.

## [1.0.0] - 2026-07-15

### Added

- Platform RTC agent API for applications that provide their own ASR, LLM, and TTS.

## [0.1.0] - 2026-05-08

### Added

- Initial SDK release.
