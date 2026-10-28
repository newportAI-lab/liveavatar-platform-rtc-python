# 更新记录

[English](./CHANGELOG.md) | **中文**

本文件记录本 SDK 的主要变化。日期为发布日期。

## [1.0.3] - 2026-10-22

1. Added: `send_external_playback(request_id, response_id, frames)` 在平台 TTS 会话中把开发者 PCM 当人声轮播放。它发送 `response.audio.start` 和 `response.audio.finish`，`data.purpose` 为 `external`。PCM 按 LiveKit 裸音频发布，不加 WebSocket 帧头。SDK 不重采样。这不是 `publish_external_audio`；后者仍是伴奏，不会替换口播。start 之后如果发布失败，仍会发送 `response.audio.finish`。平台 Dispatcher 必须接受 `purpose=external`，并按裸 PCM 转发 Agent 音轨。

## [1.0.2] - 2026-10-15

1. Added: `PlatformRTCClient` 新增可选参数 `external_audio_config`。不传则跟随本次语音格式。非 0 的 `sampleRate` 只能是 16000、24000、44100 或 48000，`channels` 为 1 或 2。开播时以 `externalAudioConfig` 发送。
2. Added: `publish_external_audio(pcm)` 是新增方法。`pcm` 为 16 位小端 PCM，只播放，不驱动口型。不要用 `publish_audio` 或 `publish_audio_stream`。它通过数据通道事件 `external.audio.chunk` 发送。采样率和声道必须与 `external_audio_config` 一致；未设置该参数时，必须与本次会话的 TTS 音频格式一致。PCM 本身不要超过 48000 字节，base64 后的数据通道消息才能保持在 65536 字节以内。后续包要在已发送音频播完前送到，第一包可以比后面的包更长，但仍不能超过该限制。
3. Added: `interrupt` 新增字符串参数 `interrupt_scope`。不传、空字符串和 `VOICE_ONLY` 停止语音播放，并取消本地语音流。`BGM_ONLY` 只清除尚未播放的外部音频，本地语音流继续。`VOICE_AND_ACCOMPANIMENT` 停止语音播放、清除尚未播放的外部音频，并取消本地语音流。取值前后的空格会被去掉，其他取值在发送前被拒绝。该参数的值写入事件 `control.interrupt` 的 `data.interruptScope`。底板视频中的音频不会被清除。
4. Changed: `scene.ready` 由平台经渲染端发出。房间里不再有 coordinator 参与者。
5. Changed: 开播字段 `onceVideoIds`、`loopVideoIds`，以及 `scene.switchVideo` 的 `onceVideos`、`loopVideos`、`videoChoreographyGroups`，原先每项只能是 resourceId。现在也可以是该数字人底板视频的 alias。alias 长度为 3 到 32，以字母开头，只含小写字母、数字和下划线，且不能以下划线结尾。SDK 原样传递。平台在播放前把 alias 换成 resourceId。

## [1.0.1] - 2026-08-06

### Added

- 资源切换消息。

## [1.0.0] - 2026-07-15

### Added

- 面向自有 ASR、LLM 和 TTS 的 Platform RTC Agent 接口。

## [0.1.0] - 2026-05-08

### Added

- SDK 首次发布。
