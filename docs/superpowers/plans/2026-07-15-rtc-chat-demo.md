# RTC Chat Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone RTC Agent chat avatar demo with developer-owned Qwen ASR, DeepSeek-compatible LLM, and Qwen realtime TTS.

**Architecture:** An aiohttp application owns one `PlatformRTCClient` session and a `ChatPipeline`. Focused provider adapters bridge DashScope callback threads to asyncio, while the pipeline serializes turns, sends RTC protocol events, and publishes 24 kHz PCM. A self-contained browser page joins the returned LiveKit room and exposes the same controls as the WebSocket chat demo.

**Tech Stack:** Python 3.11+, aiohttp, `liveavatar-platform-rtc` 1.0.0, DashScope 1.25.11+, OpenAI Python client, pytest/pytest-asyncio, vanilla HTML/JavaScript, `@sanseng/liveavatar-js-sdk` 1.0.3+

## Global Constraints

- Create files only under `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat`.
- The demo must not import or read the old `chat`, shared `frontend`, or shared `llm_client.py` at runtime.
- Support exactly one frontend user, one RTC agent, and one avatar; exclude BYO RTC, multi-user/multi-track, and multi-avatar behavior.
- Configure RTC input as 16 kHz mono PCM16 and requested output as 24 kHz mono PCM16. Require the avatar to be configured for 24 kHz output; do not add a demo-level resampler.
- Do not send `voiceId` to the platform. TTS is developer-owned.
- Wait for user join, user audio subscription, and `scene.ready` before processing a conversation.
- Missing LiveAvatar, DashScope, or LLM credentials must fail session startup explicitly.
- The target source tree has no Git metadata, so task checkpoints are test results rather than commits.

---

## File Map

- `rtc-chat/agent.py`: configuration, log buffer, RTC/session lifecycle, chat pipeline, and aiohttp routes.
- `rtc-chat/asr.py`: Qwen realtime ASR adapter and callback-to-asyncio bridge.
- `rtc-chat/llm.py`: OpenAI-compatible streaming chat client and bounded history.
- `rtc-chat/tts.py`: Qwen realtime TTS adapter and PCM callback-to-async-iterator bridge.
- `rtc-chat/index.html`: standalone LiveAvatar browser client and controls.
- `rtc-chat/package.json`: local JS SDK dependency.
- `rtc-chat/requirements.txt`: standalone Python dependencies and local RTC SDK install instruction.
- `rtc-chat/QUICKSTART.md`: environment, installation, run, and smoke-test instructions.
- `rtc-chat/tests/fakes.py`: fake RTC and provider collaborators.
- `rtc-chat/tests/test_asr.py`: ASR callback and audio forwarding tests.
- `rtc-chat/tests/test_llm.py`: history and streamed delta tests.
- `rtc-chat/tests/test_tts.py`: PCM decode, finish, and cancel tests.
- `rtc-chat/tests/test_agent.py`: readiness, protocol events, interruption, HTTP, and cleanup tests.

---

### Task 1: Standalone configuration and LLM adapter

**Files:**
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/llm.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/requirements.txt`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_llm.py`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`, `Settings.validate() -> None`.
- Produces: `LlmClient.stream_reply(user_text: str, on_delta: Callable[[str], Awaitable[None]]) -> str` and `reset() -> None`.

- [ ] **Step 1: Write failing configuration and LLM tests**

```python
# tests/test_llm.py
import pytest
from agent import Settings
from llm import LlmClient

def test_settings_reject_missing_credentials():
    settings = Settings("", "", None, "", "", "", "", "", "", 8080)
    with pytest.raises(ValueError, match="LIVEAVATAR_API_KEY"):
        settings.validate()

@pytest.mark.asyncio
async def test_stream_reply_forwards_deltas_and_retains_history(fake_openai):
    client = LlmClient(api_key="key", base_url="https://llm.test", model="model",
                       system_prompt="system", client=fake_openai(["你", "好"]))
    deltas = []
    reply = await client.stream_reply("hello", deltas.append)
    assert reply == "你好"
    assert deltas == ["你", "好"]
    assert client.messages[-2:] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "你好"},
    ]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat && pytest tests/test_llm.py -q`

Expected: import failure because `agent.py` and `llm.py` do not exist.

- [ ] **Step 3: Implement settings and the minimal streaming LLM client**

```python
# llm.py core interface
class LlmClient:
    def __init__(self, *, api_key, base_url, model, system_prompt, client=None):
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._system_prompt = system_prompt
        self.messages = [{"role": "system", "content": system_prompt}]
        self._lock = asyncio.Lock()

    async def stream_reply(self, user_text, on_delta):
        async with self._lock:
            self.messages.append({"role": "user", "content": user_text})
            self.messages = [self.messages[0]] + self.messages[-20:]
            stream = await self._client.chat.completions.create(
                model=self._model, messages=self.messages, stream=True,
                max_tokens=512, temperature=0.7)
            parts = []
            async for chunk in stream:
                text = chunk.choices[0].delta.content
                if text:
                    parts.append(text)
                    result = on_delta(text)
                    if inspect.isawaitable(result):
                        await result
            reply = "".join(parts)
            if reply.strip():
                self.messages.append({"role": "assistant", "content": reply})
            return reply

    def reset(self):
        self.messages = [{"role": "system", "content": self._system_prompt}]
```

Implement `Settings` as a frozen dataclass populated from the exact environment variables in the design. `validate()` checks required values in this order: `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`, `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`.

Set `requirements.txt` to:

```text
aiohttp>=3.9
dashscope>=1.25.11
openai>=1.0.0
pytest>=8.0
pytest-asyncio>=0.23
liveavatar-platform-rtc @ file:///Users/luffer/workspace/liveavatar-platform-rtc-python
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_llm.py -q`

Expected: all tests pass.

---

### Task 2: Qwen realtime ASR adapter

**Files:**
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/asr.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_asr.py`

**Interfaces:**
- Consumes: RTC `AudioFrame.data` containing 16 kHz mono PCM16.
- Produces: `QwenAsr.connect()`, `feed_audio(frame: AudioFrame)`, and `close()`.
- Produces callbacks `on_speech_started`, `on_speech_stopped`, `on_partial(text)`, `on_final(text)`, and `on_error(message)` on the owning asyncio loop.

- [ ] **Step 1: Write failing callback and audio tests**

```python
@pytest.mark.asyncio
async def test_feed_audio_encodes_pcm(fake_conversation, audio_frame):
    asr = make_asr(fake_conversation)
    await asr.connect()
    asr.feed_audio(audio_frame)
    fake_conversation.append_audio.assert_called_once_with(
        base64.b64encode(audio_frame.data.tobytes()).decode("ascii"))

@pytest.mark.asyncio
async def test_callback_dispatches_final_on_event_loop(callback, final_texts):
    callback.on_event({"type": "conversation.item.input_audio_transcription.completed",
                       "transcript": "你好"})
    await asyncio.sleep(0)
    assert final_texts == ["你好"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_asr.py -q`

Expected: import failure for `asr.QwenAsr`.

- [ ] **Step 3: Implement the adapter around DashScope**

Use `OmniRealtimeConversation`, `OmniRealtimeCallback`, and `TranscriptionParams`. In `connect()`, run blocking `conversation.connect` with `asyncio.to_thread`, then configure:

```python
conversation.update_session(
    output_modalities=[MultiModality.TEXT],
    enable_turn_detection=True,
    turn_detection_type="server_vad",
    turn_detection_threshold=0.0,
    turn_detection_silence_duration_ms=400,
    enable_input_audio_transcription=True,
    transcription_params=TranscriptionParams(
        language="zh", sample_rate=16000, input_audio_format="pcm"),
)
```

Implement callback dispatch with `asyncio.run_coroutine_threadsafe()` for coroutine callbacks and `loop.call_soon_threadsafe()` for synchronous callbacks. Ignore empty partial/final strings. Make `close()` idempotent and run the blocking provider close in a thread.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_asr.py -q`

Expected: all tests pass.

---

### Task 3: Qwen realtime TTS adapter and PCM streaming

**Files:**
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tts.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`

**Interfaces:**
- Produces: `QwenTts.start() -> None`, `append_text(text: str) -> None`, `finish() -> None`, `cancel() -> None`, `close() -> None`.
- Produces: `frames() -> AsyncIterator[AudioFrame]`, yielding 24 kHz mono PCM16.

- [ ] **Step 1: Write failing PCM and cancellation tests**

```python
@pytest.mark.asyncio
async def test_audio_delta_yields_pcm_frame(tts, callback):
    pcm = b"\x01\x00\x02\x00"
    callback.on_event({"type": "response.audio.delta",
                       "delta": base64.b64encode(pcm).decode("ascii")})
    frame = await anext(tts.frames())
    assert frame.sample_rate == 24000
    assert frame.num_channels == 1
    assert frame.data.tobytes() == pcm

@pytest.mark.asyncio
async def test_cancel_discards_late_audio(tts, callback, provider):
    await tts.cancel()
    callback.on_event({"type": "response.audio.delta", "delta": "AQI="})
    assert tts.audio_queue.empty()
    provider.clear_appended_text.assert_called_once()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_tts.py -q`

Expected: import failure for `tts.QwenTts`.

- [ ] **Step 3: Implement realtime TTS**

Construct `QwenTtsRealtime(model=model, callback=callback, url=url)`. Run `connect()` in a thread and call:

```python
provider.update_session(
    voice=voice,
    response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
    mode="server_commit",
)
```

Decode `response.audio.delta` with `base64.b64decode`, wrap it with `AudioFrame.from_pcm(pcm, sample_rate=24000)`, and enqueue it on the event loop. Enqueue a private sentinel on `response.done`, `session.finished`, or error. `frames()` stops at the sentinel. `cancel()` first marks the current generation inactive, calls `clear_appended_text()`, drains queued frames, and enqueues the sentinel so late audio cannot leak into the next response.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_tts.py -q`

Expected: all tests pass.

---

### Task 4: RTC chat pipeline, readiness, protocol events, and interruption

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/fakes.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Consumes: `Session.on`, waiters, `publish_audio_stream`, data-event helpers, and `interrupt`.
- Consumes: the ASR/LLM/TTS interfaces from Tasks 1-3.
- Produces: `ChatPipeline.start()`, `interrupt(request_id=None)`, and `close()`.

- [ ] **Step 1: Write failing readiness and audio-forwarding tests**

```python
@pytest.mark.asyncio
async def test_start_waits_for_all_rtc_readiness(fake_session, pipeline):
    await pipeline.start()
    assert fake_session.wait_calls == ["user", "user_audio", "scene_ready"]

@pytest.mark.asyncio
async def test_user_audio_is_forwarded_to_asr(fake_session, pipeline, frame):
    await pipeline.start()
    await fake_session.emit("user_audio_frame", frame)
    pipeline.asr.feed_audio.assert_called_once_with(frame)
```

- [ ] **Step 2: Write failing protocol and interruption tests**

```python
@pytest.mark.asyncio
async def test_asr_final_streams_subtitle_tts_and_audio(pipeline, fake_session):
    await pipeline.on_speech_started()
    request_id = pipeline.request_id
    await pipeline.on_asr_final("天气如何")
    fake_session.send_asr_final.assert_awaited_once_with(request_id, "天气如何")
    fake_session.send_subtitle.assert_any_await(
        request_id, pipeline.response_id, "晴", 0, ANY)
    fake_session.publish_audio_stream.assert_awaited_once()

@pytest.mark.asyncio
async def test_interrupt_cancels_all_turn_outputs(pipeline, fake_session):
    pipeline.response_task = asyncio.create_task(asyncio.sleep(60))
    await pipeline.interrupt("req-1")
    assert pipeline.response_task.cancelled()
    pipeline.tts.cancel.assert_awaited_once()
    fake_session.interrupt.assert_awaited_once_with("req-1")
```

- [ ] **Step 3: Implement `ChatPipeline`**

Register `user_audio_frame` before waiting, then call the three waiters in order and connect ASR. On VAD start, interrupt any active response, create a UUID request ID, reset partial sequence, and send voice start. On partial/final callbacks, send the matching session event. A final result creates a UUID response ID and one response task:

```python
async def _run_response(self, text, request_id, response_id):
    await self.tts.start()
    audio_task = asyncio.create_task(
        self.session.publish_audio_stream(self.tts.frames()))
    seq = 0
    async def on_delta(delta):
        nonlocal seq
        await self.session.send_subtitle(
            request_id, response_id, delta, seq, int(time.time() * 1000))
        self.tts.append_text(delta)
        seq += 1
    try:
        reply = await self.llm.stream_reply(text, on_delta)
        self.tts.finish()
        await audio_task
        self.conversation.extend([
            {"role": "user", "text": text},
            {"role": "agent", "text": reply},
        ])
    finally:
        if not audio_task.done():
            audio_task.cancel()
        await asyncio.gather(audio_task, return_exceptions=True)
```

Protect turn replacement with an asyncio lock and a monotonically increasing generation number; every callback checks its captured generation before publishing. `close()` is idempotent and closes ASR/TTS after interrupting the response.

- [ ] **Step 4: Run pipeline tests**

Run: `pytest tests/test_agent.py -q`

Expected: readiness, media, event, interruption, and cleanup tests pass.

---

### Task 5: HTTP application and standalone browser

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/index.html`
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/package.json`
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Produces the five HTTP endpoints and `/sdk.js` defined in the design.
- Produces `create_app(settings, client_factory, provider_factories) -> web.Application` for testing.

- [ ] **Step 1: Write failing route tests**

```python
async def test_start_session_returns_frontend_credentials(aiohttp_client, app):
    client = await aiohttp_client(app)
    response = await client.post("/api/start-session")
    assert response.status == 200
    assert await response.json() == {
        "success": True, "userToken": "user-token",
        "sfuUrl": "wss://sfu.test", "sessionId": "session-1"}

async def test_second_start_stops_previous_session(aiohttp_client, app, rtc_clients):
    client = await aiohttp_client(app)
    await client.post("/api/start-session")
    await client.post("/api/start-session")
    rtc_clients[0].disconnect.assert_awaited_once()
```

- [ ] **Step 2: Implement application lifecycle and routes**

Create `PlatformRTCClient` with `input_sample_rate=16000`, `output_sample_rate=24000`, no voice ID, and the configured base URL. Return `session.frontend_connection.user_token` and `.sfu_url`. Start readiness/pipeline work in a tracked task so the HTTP response does not wait for the browser to join. Route interrupt through `ChatPipeline.interrupt`; shutdown calls the same idempotent stop routine.

- [ ] **Step 3: Add the standalone frontend and package manifest**

Copy the old chat page's visible layout and controls, then keep only these backend assumptions:

```javascript
const started = await fetch('/api/start-session', {method: 'POST'}).then(r => r.json());
avatar = new LiveAvatarSDK.LiveAvatar({
  connectConfig: {type: 'direct', config: {
    sfuUrl: started.sfuUrl, userToken: started.userToken
  }}
});
await avatar.connect();
```

Keep microphone publication, track rendering, interrupt, stop, logs, and ratio toggle behavior from the source page. Set `package.json` dependency to `"@sanseng/liveavatar-js-sdk": "^1.0.3"`. Serve only `rtc-chat/node_modules/@sanseng/liveavatar-js-sdk/dist/index.full.umd.js` from `/sdk.js`.

- [ ] **Step 4: Run route tests and static independence check**

Run: `pytest tests/test_agent.py -q`

Run: `rg -n "\.\./chat|\.\./\.\./frontend|from llm_client|import llm_client" . -g '!QUICKSTART.md'`

Expected: route tests pass and `rg` returns no matches.

---

### Task 6: Quickstart, complete verification, and live smoke-test instructions

**Files:**
- Create: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/QUICKSTART.md`
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Documents the complete standalone install and run contract.

- [ ] **Step 1: Add the final cleanup regression test**

```python
@pytest.mark.asyncio
async def test_stop_is_idempotent(runtime):
    await runtime.stop()
    await runtime.stop()
    runtime.pipeline.close.assert_awaited_once()
    runtime.rtc_client.disconnect.assert_awaited_once()
```

- [ ] **Step 2: Write `QUICKSTART.md` with exact commands**

Document:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
export LIVEAVATAR_API_KEY="..."
export LIVEAVATAR_AVATAR_ID="..."
export DASHSCOPE_API_KEY="..."
export DEEPSEEK_API_KEY="..."
python agent.py
```

List optional TTS model/voice/URL and LLM variables, expected 16 kHz input and 24 kHz PCM output, browser steps, and troubleshooting for missing keys, missing `node_modules`, absent `scene.ready`, ASR silence, and TTS connection failure.

- [ ] **Step 3: Run the entire offline verification suite**

Run: `pytest -q`

Expected: all RTC Chat tests pass.

Run: `python -m compileall -q agent.py asr.py llm.py tts.py tests`

Expected: exit code 0 with no output.

Run: `rg -n "liveavatar_channel_sdk|AvatarAgent|developer_tts|voice_id|voiceId" . -g '*.py'`

Expected: no matches.

- [ ] **Step 4: Perform the credentialed smoke test when credentials are available**

Run `python agent.py`, open `http://localhost:8080`, connect, start the microphone, ask one question, interrupt a second answer, and disconnect. Verify logs show user join, user audio subscription, `scene.ready`, ASR final, LLM deltas, TTS PCM publication, interruption, and clean shutdown. If credentials are unavailable, report this step as not run rather than claiming it passed.
