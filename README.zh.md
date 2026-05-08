# Live Avatar Platform RTC Python SDK

[English](README.md)

Live Avatar **平台 RTC** 模式的 Python Agent SDK。以 `agent_{sessionId}` 身份加入平台 LiveKit 房间，驱动实时数字人。开发者提供 ASR 和 LLM，TTS 通常由平台提供（也可自带以降低延迟）。

SDK 运行在开发者后端，通过 **RTC Track** 收发音频、**Data Channel** 收发控制事件。

```
                   平台 LiveKit SFU
                   ╔═══════════════╗
 user ──Audio──▶   ║               ║──Audio──▶ agent (本 SDK)
 user ◀─Video+Audio ║               ║◀─Audio── agent (TTS)
 user ──Data Ch.──▶ ║               ║──Data Ch.──▶ agent
                   ╚═══════════════╝
                        │
                   renderer (平台管理，订阅 agent Audio Track 驱动口型)
```

## 安装

```bash
pip install liveavatar-platform-rtc
```

依赖：Python ≥ 3.10，LiveKit 访问由平台提供。

## 快速开始

```python
from liveavatar_rtc import PlatformRTCClient, AudioFrame, USER_AUDIO_FRAME

client = PlatformRTCClient(api_key="lf_...", avatar_id="avatar-xxx")

async with client as session:
    @session.on(USER_AUDIO_FRAME)
    async def on_audio(frame: AudioFrame):
        # ASR → LLM → TTS → 发布音频驱动口型
        # await session.publish_audio(tts_output_frame)
        pass
```

## 音频订阅

Agent 自动订阅身份以 `"user"` 开头的参与者的 **RemoteAudioTrack**（即 `user_*`）。其他所有 Track——视频、agent 音频、非 user 参与者——均被忽略。订阅的音频会重采样到配置的 `sample_rate`（默认 16kHz mono int16），以 `USER_AUDIO_FRAME` 事件分发。

## 架构

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
│  事件注册 on(...)                                  │
│  publish_audio() / send_response_*() / interrupt() │
└──────┬──────────────────────┬───────────────────┘
       │                      │
┌──────▼────────┐   ┌─────────▼──────────────────┐
│   ApiClient   │   │     LiveKitManager          │
│               │   │                             │
│ POST /v1/     │   │  Room 加入/离开              │
│  session/start│   │  Audio Track 订阅 (user)     │
│  session/stop │   │  Audio Track 发布 (agent)    │
└───────────────┘   │  Data Channel 收发           │
                    │  EventDispatcher             │
                    └─────────────────────────────┘
```

## API 参考

### PlatformRTCClient

```python
client = PlatformRTCClient(
    api_key="lf_...",                   # 平台 API Key
    avatar_id="avatar-xxx",             # 数字人 ID
    base_url="https://facemarket.ai/vih/dispatcher",  # 可选
    sample_rate=16000,                   # 音频采样率，默认 16kHz
    sandbox=False,                       # 沙箱模式
)

# Context manager（推荐）
async with client as session:
    ...

# 或显式调用
session = await client.connect()
await client.disconnect()
```

`connect()` 内部流程：`POST /v1/session/start` → 获取 token/sfuUrl → 连接 LiveKit → 等待 user 加入 → 返回 Session。

#### 连接生命周期

```python
@client.on("connection_established")
async def on_connected(session): ...

@client.on("connection_closed")
async def on_closed(session_id): ...
```

### Session — 事件注册

```python
@session.on(event_name)
async def handler(data): ...
```

#### 入站事件（Data Channel，user/coordinator → agent）

| 常量 | 事件名 | 说明 |
|------|--------|------|
| `INPUT_TEXT` | `"input.text"` | 用户文本输入 |
| `SCENE_READY` | `"scene.ready"` | 用户画面就绪 |
| `SESSION_STATE` | `"session.state"` | 会话状态变更（IDLE / LISTENING / THINKING / SPEAKING） |
| `SESSION_CLOSING` | `"session.closing"` | 会话即将关闭 |
| `IDLE_TRIGGER` | `"system.idleTrigger"` | 用户长时间无操作，可调用 `send_prompt()` 主动说话 |
| `ERROR` | `"error"` | 平台/coordinator 错误 |

#### 入站事件（RTC Track，SDK 级）

| 常量 | 事件名 | 说明 |
|------|--------|------|
| `USER_AUDIO_FRAME` | `"user_audio_frame"` | 用户音频 PCM 帧（已重采样到配置的 sample_rate） |
| `USER_AUDIO_TRACK_SUBSCRIBED` | `"user_audio_track_subscribed"` | 用户 Audio Track 就绪 |
| `USER_JOINED` | `"user_joined"` | 用户加入房间 |
| `DISCONNECTED` | `"disconnected"` | LiveKit 连接断开 |

### Session — TTS 输出

#### 开发者提供 TTS（发布 Audio Track）

```python
# 发布 PCM 音频帧到 agent Audio Track，renderer 自动订阅驱动口型
await session.publish_audio(frame: AudioFrame)
```

#### 平台提供 TTS（Data Channel 文本流）

```python
request_id = await session.send_response_start(config: TTSConfig | None) → str
await session.send_response_chunk(request_id, text)
await session.send_response_done(request_id)
await session.send_response_cancel(request_id)          # 取消进行中的回复
```

#### 字幕

```python
# 发送字幕文本到前端（使用 response.chunk，前端展示为字幕）
await session.send_subtitle(request_id, text)
```

### Session — 开发者 TTS 音频生命周期

使用开发者 TTS 通过 `publish_audio()` 推送音频时，用生命周期事件包裹音频流，以便 coordinator 驱动状态机：

```python
# 正常对话回复 — 包裹 publish_audio()
req_id = await session.send_response_audio_start()
# ... 流式 TTS PCM 通过 await session.publish_audio() ...
await session.send_response_audio_finish(req_id)

# 空闲唤起 / 推送提醒 — 包裹 publish_audio()
req_id = await session.send_response_audio_prompt_start()
# ... 流式 TTS PCM 通过 await session.publish_audio() ...
await session.send_response_audio_prompt_finish(req_id)
```

`promptStart`/`promptFinish` 变体告知 coordinator 这是由 `system.idleTrigger` 触发的主动播报，而非用户请求的回复。

### Session — 开发者 ASR

```python
await session.send_asr_partial(text)   # 中间结果 → 前端字幕
await session.send_asr_final(text)     # 最终结果 → 前端 + coordinator
```

### Session — 开发者 VAD（使用开发者 ASR 时必需）

自行提供 ASR 时**必须**发送 VAD 边界事件，coordinator 依赖它们驱动状态机：

```python
# ── 在 ASR 管线前后调用 ──
await session.send_voice_start()       # 用户开始说话（VAD 开始）
# ... ASR 处理 ...
await session.send_voice_finish()      # 用户停止说话（VAD 结束）
```

缺少这些事件，coordinator 无法在 LISTENING / THINKING / SPEAKING 状态间正确切换。

### Session — 控制

```python
await session.interrupt()                      # 打断当前播报
await session.send_prompt("你好，最近怎么样？")  # 触发数字人主动说话
```

### Session — 错误上报

```python
await session.send_error("E001", "TTS 服务不可用")
```

### Session — 生命周期

```python
await session.wait_until_ready(timeout=30.0)   # 等待 user 加入
await session.close()                            # 退出房间、释放资源
```

## 数据类型

### AudioFrame

```python
@dataclass
class AudioFrame:
    data: np.ndarray      # PCM int16 samples
    sample_rate: int      # Hz
    num_channels: int     # 1 = mono
    timestamp: int = 0    # LiveKit timestamp (μs)

    # 工厂方法
    AudioFrame.from_pcm(pcm: bytes, sample_rate: int, num_channels: int = 1) → AudioFrame
    AudioFrame.from_ndarray(data: np.ndarray, sample_rate: int, timestamp: int = 0) → AudioFrame

    # 序列化
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

## 完整集成示例

### 语音对话（开发者 ASR + LLM + TTS）

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
            # 1. ASR：frame.data (int16 PCM) → 文本
            text = await my_asr(frame.data)
            await session.send_voice_start()
            await session.send_asr_partial(text)
            await session.send_asr_final(text)
            await session.send_voice_finish()

            # 2. LLM → 回复
            reply = await my_llm(text)

            # 3. TTS → PCM → 发布，用音频生命周期包裹
            req_id = await session.send_response_audio_start()
            pcm = await my_tts(reply)
            await session.publish_audio(AudioFrame.from_pcm(pcm, sample_rate=24000))
            await session.send_response_audio_finish(req_id)

        @session.on(INPUT_TEXT)
        async def on_text(data: dict):
            reply = await my_llm(data.get("text", ""))
            # 使用平台 TTS
            req_id = await session.send_response_start(TTSConfig(speed=1.0))
            await session.send_response_chunk(req_id, reply)
            await session.send_response_done(req_id)

        @session.on(IDLE_TRIGGER)
        async def on_idle(_data):
            prompt = await my_idle_prompt()
            await session.send_prompt(prompt)

        @session.on(SESSION_STATE)
        async def on_state(data: dict):
            print(f"状态: {data.get('state')}")

        @session.on(ERROR)
        async def on_error(data: dict):
            print(f"错误: {data}")

        await session.wait_until_ready()
        print(f"Agent 就绪，session={session.session_id}")

        disconnect_event = asyncio.Event()

        @session.on(DISCONNECTED)
        async def wait_disconnect(reason):
            print(f"断开连接: {reason}")
            disconnect_event.set()

        await disconnect_event.wait()

asyncio.run(main())
```

### 平台 TTS 模式（开发者只需回文本）

```python
async with client as session:

    @session.on(USER_AUDIO_FRAME)
    async def on_audio(frame: AudioFrame):
        text = await my_asr(frame.data)
        reply = await my_llm(text)

        # TTS 由平台合成，开发者只回文本
        req_id = await session.send_response_start(TTSConfig(speed=1.2, mood="cheerful"))
        await session.send_response_chunk(req_id, reply)
        await session.send_response_done(req_id)

    await session.wait_until_ready()
    await asyncio.Event().wait()  # 持续运行
```

## 与 WebSocket SDK 的差异

本 SDK 与 [`liveavatar-channel-python`](https://github.com/newportAI-lab/liveavatar-channel-python)（WebSocket 协议）事件命名完全一致，业务代码可复用。

| 维度 | WebSocket SDK | 本 SDK (Platform RTC) |
|------|-------------|----------------------|
| 传输层 | WebSocket binary + JSON | LiveKit RTC Track + Data Channel |
| 音频接收 | Binary Frame（字节流） | Audio Track 订阅（PCM 帧） |
| 音频发送 | Binary Frame | Audio Track 发布 |
| Identity | 无房间概念 | `agent_{sessionId}` |
