# RTC Chat Demo Design

## Goal

Create a self-contained `rtc-chat` demo under
`/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/` that
matches the existing WebSocket `chat` demo's conversational behavior while
using the Platform RTC Agent SDK and a fully developer-owned ASR, LLM, and TTS
pipeline.

The demo covers one frontend user, one RTC agent, and one avatar. It does not
include BYO RTC, multiple users or tracks, or multiple avatars.

## Directory Layout

```text
rtc-chat/
├── agent.py
├── asr.py
├── llm.py
├── tts.py
├── index.html
├── package.json
├── requirements.txt
├── QUICKSTART.md
└── tests/
```

The directory is runtime-independent of the existing `chat` demo, shared
`frontend` directory, and shared `llm_client.py`. Its `package.json` installs
`@sanseng/liveavatar-js-sdk`, and its HTTP server exposes the locally installed
browser bundle as `/sdk.js`.

## Components

### HTTP and RTC orchestration

`agent.py` owns the aiohttp application, one active `PlatformRTCClient`, and
the current conversation pipeline. It exposes the same browser-facing
operations as the WebSocket demo:

- `POST /api/start-session`
- `POST /api/stop-session`
- `POST /api/interrupt`
- `GET /api/logs`
- `POST /api/clear-logs`

Starting a session connects the backend RTC agent first and returns the
session's frontend `userToken`, `sfuUrl`, and `sessionId`. The pipeline begins
consuming media only after the frontend user joins, a user audio track is
subscribed, and `scene.ready` is received.

### ASR

`asr.py` wraps DashScope Qwen realtime ASR. RTC user audio arrives as 16 kHz,
mono PCM16 and is appended to the ASR session. ASR callback threads hand work
back to the asyncio event loop safely.

VAD and transcription events map to RTC data events:

- speech start: `input.voice.start`
- interim transcript: `input.asr.partial`
- speech stop: `input.voice.finish`
- final transcript: `input.asr.final`

There is no platform ASR fallback. A missing DashScope credential is a startup
configuration error.

### LLM

`llm.py` wraps an OpenAI-compatible async chat completion client. Defaults use
DeepSeek configuration, while environment variables may select another
compatible endpoint and model. It retains the system prompt plus the latest 20
conversation messages and streams response deltas.

### TTS

`tts.py` wraps DashScope Qwen realtime TTS. The defaults are:

- model: `qwen3-tts-flash-realtime`
- voice: `Cherry`
- output: 24 kHz, mono, signed 16-bit PCM
- interaction mode: `server_commit`

The model and voice are configurable through environment variables. LLM deltas
are appended to the active TTS request. PCM callbacks are converted into RTC
SDK `AudioFrame` objects without another codec layer; the SDK and LiveKit own
real-time buffering, resampling where negotiated, and Opus transport.

### Frontend

`index.html` preserves the existing chat demo's user-visible behavior:

- connect and disconnect
- start and stop microphone publication
- avatar video rendering
- connection and session status
- user ASR text and avatar response subtitles
- manual interrupt
- live logs and log clearing
- portrait and landscape display toggle

The frontend receives only the frontend LiveKit credential and SFU URL. It
never receives the platform API key or backend agent credential.

## Data Flow

1. The browser calls `POST /api/start-session`.
2. The backend creates a Platform RTC session and returns frontend connection
   data.
3. The browser joins the same LiveKit room and publishes its microphone.
4. The backend waits for the user, user audio subscription, and `scene.ready`.
5. RTC audio frames feed Qwen ASR.
6. A final transcript starts one DeepSeek response turn.
7. LLM deltas are sent as `response.chunk` subtitle events and appended to
   Qwen realtime TTS.
8. TTS PCM frames are published through the RTC SDK and rendered by the avatar.
9. The completed user and assistant texts are appended to conversation history.

Only one response turn may generate or publish audio at a time.

## Interruption

An interrupt can originate from Qwen VAD detecting new user speech or from the
frontend interrupt endpoint. Both paths use one idempotent operation that:

1. cancels the active LLM task;
2. stops and discards the active TTS response;
3. calls `Session.interrupt(request_id)` to cancel SDK publication, clear queued
   audio, and send `control.interrupt`;
4. prevents late callbacks from the cancelled turn from publishing subtitles
   or audio.

The next ASR final result creates a fresh request and response identifier.

## Lifecycle and Errors

The application rejects session startup when required LiveAvatar, DashScope,
or LLM credentials are missing. Provider errors are logged with their request
context and terminate only the current response when the RTC session remains
healthy.

Stopping a session or shutting down the HTTP application cancels the readiness
task, current response, ASR and TTS connections, audio publication, RTC session,
and HTTP clients. Cleanup is safe to call more than once. A browser may start a
new session after cleanup; starting while another session is active first
stops the old session.

## Configuration

Required environment variables:

- `LIVEAVATAR_API_KEY`
- `LIVEAVATAR_AVATAR_ID`
- `DASHSCOPE_API_KEY`
- `DEEPSEEK_API_KEY`

Optional variables include `LIVEAVATAR_BASE_URL`, `HTTP_PORT`,
`DASHSCOPE_ASR_MODEL`, `DASHSCOPE_ASR_URL`, `DASHSCOPE_TTS_MODEL`,
`DASHSCOPE_TTS_VOICE`, `DASHSCOPE_TTS_URL`, `DEEPSEEK_BASE_URL`,
`DEEPSEEK_MODEL`, and `SYSTEM_PROMPT`.

The RTC client explicitly requests 16 kHz input and 24 kHz output. This demo
requires the avatar to be created with a 24 kHz output sample rate because its
Qwen realtime TTS stream is fixed to 24 kHz PCM. If platform negotiation
selects another output rate, audio publication fails with a message directing
the developer to align the avatar configuration; the demo does not add its own
resampler.

## Testing and Acceptance

Unit tests use fake RTC sessions and provider objects; they do not require API
keys or network access. Tests cover:

- session start response and readiness ordering;
- forwarding RTC PCM frames into ASR;
- VAD, partial ASR, and final ASR data events;
- LLM delta forwarding to subtitles and TTS;
- 24 kHz mono PCM conversion into `AudioFrame` objects;
- interruption cancelling LLM, TTS, subtitles, and queued playout;
- repeated stop and application shutdown cleanup;
- configuration validation.

Acceptance requires all unit tests and Python compilation checks to pass, and
a static check to show that `rtc-chat` contains no runtime imports or file reads
from the WebSocket `chat`, shared frontend, or shared LLM modules. A live smoke
test is documented but requires the developer's real provider credentials and
platform access.
