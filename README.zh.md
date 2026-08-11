# Live Avatar Platform RTC Python SDK

[English](README.md)

这是 Live Avatar **Platform RTC** 模式的后端 Agent SDK。ASR、LLM 和 TTS
全部由开发者应用负责；SDK 将这些管线接入平台 LiveKit 房间：用户音频以 PCM
帧进入后端，开发者生成的 TTS PCM 音频驱动数字人说话。本包不提供平台 TTS
或文本输入兼容 API。

**版本 1.0.1** —— 面向开发者自有 ASR/LLM/TTS 管线的破坏性 Platform RTC
Agent API。

## 安装

```bash
pip install liveavatar-platform-rtc
```

需要 Python 3.10 或更高版本。

## 开发安装

```bash
pip install -e ".[dev]"
```

## 最小示例

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
    print(session.frontend_connection)  # 分发给前端
    pipeline_input: asyncio.Queue[AudioFrame] = asyncio.Queue()

    @session.on("user_audio_frame")
    async def on_user_audio(frame: AudioFrame) -> None:
        # 输入开发者的 ASR/Omni，再发布开发者自己的 TTS 音频。
        await pipeline_input.put(frame)

    await session.wait_for_user(timeout=30)
    await session.wait_for_scene_ready(timeout=30)
    await asyncio.Event().wait()
```

[`examples/basic_agent.py`](examples/basic_agent.py) 提供了语法可运行、无需外部
AI 服务的管线骨架。它会连接房间并消费用户音频，但在接入真实的开发者 ASR、
LLM 和 TTS 前会刻意不生成数字人语音；程序启动时也会打印此警告。

完整 Platform RTC 协议模型见 [`PROTOCOL.zh.md`](PROTOCOL.zh.md)。

## 连接与就绪阶段

1. `await client.connect()`（或进入异步上下文）创建平台会话，并让后端 Agent
   连接 LiveKit。
2. 将 `session.frontend_connection` 发给前端。其中只有用户的 `user_token` 和
   `sfu_url`；不得发送 API Key 或 Agent Token。
3. `await session.wait_for_user()` 等待前端用户加入同一房间。
4. `await session.wait_for_scene_ready()` 等待 `scene.ready` 事件（由平台通过 renderer 发送）；
   此后再开始数字人音频输出。

可观察状态包括 `is_agent_connected`、`is_user_joined`、
`is_user_audio_subscribed`、`is_scene_ready`、`is_closing` 和 `is_closed`。
等待超时抛出 `SessionWaitTimeoutError`，等待期间关闭则抛出
`SessionClosedError`。

## 开发者自有音频管线

SDK 通过 `user_audio_frame` 发送单声道 PCM16，并重采样到
`input_sample_rate`（默认 16 kHz），可直接交给开发者的 ASR 或 Omni 模型。
LLM 与 TTS 也完全运行在开发者后端。

使用 `await session.publish_audio(frame)` 发布单帧，或使用
`await session.publish_audio_stream(frames)` 流式发布异步迭代器。输出必须为
单声道 PCM16，且采样率与协商值一致。推荐值和客户端默认值是 24 kHz；会话
启动响应可以覆盖 `output_sample_rate`，SDK 会按服务端最终值校验。实时播放
缓冲和 Opus 编码由 LiveKit 负责，应用无需自行编码 Opus。

```python
async def tts_frames():
    async for pcm in my_streaming_tts():
        yield AudioFrame.from_pcm(pcm, sample_rate=24000)

await session.publish_audio_stream(tts_frames())
```

同一时间只能有一个输出流。`await session.interrupt(request_id)` 会取消该流、
清空待播放音频、发送 `control.interrupt`，并触发本地 `interrupted` 钩子。
应用应在该钩子中同时取消正在生成的 LLM/TTS 请求。

## 事件与协议钩子

使用 `@session.on(event_name)` 注册处理器。常用事件包括
`USER_AUDIO_FRAME`、`USER_JOINED`、`USER_LEFT`、`SCENE_READY`、
`SCENE_RESOURCE_TRANSITION`、`SESSION_STATE`、`SESSION_CLOSING`、`DISCONNECTED`、`ERROR` 和
`CUSTOM_EVENT`。未知 Data Channel 事件会作为 `CUSTOM_EVENT` 转发，并保留
原始元数据。

平台会在 renderer 播放完当前视频、即将切换到下一个已配置视频资源时发送
`SCENE_RESOURCE_TRANSITION`。这是单向通知；handler 返回值不会确认、取消或延迟
renderer 的视频切换。

```python
from liveavatar_rtc import DataChannelEvent, SCENE_RESOURCE_TRANSITION

@session.on(SCENE_RESOURCE_TRANSITION)
async def on_resource_transition(event: DataChannelEvent) -> None:
    previous_id = event.data["previousResourceId"]
    next_id = event.data["nextResourceId"]
    message = event.data.get("message")
```

`previousResourceId` 和 `nextResourceId` 是必填的稳定业务资源 ID，不是 URL、
文件路径或展示名称。`message` 是可选的可读说明文本，仅适合日志或排查，不要用它做
业务分支判断。`session_id`、`request_id`、`timestamp`、participant identity
和 topic 都是 `DataChannelEvent` 上的 envelope 元数据，不在 `data` 内。事件没有
`streamId` 字段，因为当前 RTC session 已经限定了 stream 范围。

开发者 ASR/VAD 与应用自定义观测管线可调用：

```python
await session.send_voice_start(request_id)
await session.send_asr_partial(request_id, text, seq)
await session.send_voice_finish(request_id)
await session.send_asr_final(request_id, text)
await session.send_custom_event("vendor.event", {"value": 1})
```

RTC SDK 不提供 `response.chunk` / `response.done` helper。数字人语音由开发者
发布到 LiveKit 的音频 Track 驱动，不由平台文本 TTS 驱动。如应用需要字幕或
诊断信息，请发送你自己的前后端明确理解的自定义事件。

使用 `await session.close()` 或退出客户端上下文关闭连接；上下文管理器还会停止
远端平台会话。

## 适用范围

本包仅面向 Platform RTC 后端 Agent，通过 LiveKit 音频 Track 传输 PCM，
通过 LiveKit Data Channel 传输结构化控制事件。其公开接口仅包含 v2 Platform
RTC Agent API，不包含旧版兼容别名。
