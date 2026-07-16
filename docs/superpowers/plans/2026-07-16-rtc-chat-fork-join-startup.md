# RTC Chat Fork/Join Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce rtc-chat startup latency by connecting ASR and long-lived TTS concurrently with RTC readiness.

**Architecture:** `ChatPipeline.start()` registers handlers, forks `rtc_ready`, `asr_ready`, and `tts_ready`, then joins all three before setting `_ready = True`. `QwenTts` gains a startup-time `connect()` method that creates and configures a reusable provider; per-turn `start()` becomes a generation boundary that reuses the connected provider.

**Tech Stack:** Python 3.14, asyncio, aiohttp, DashScope Qwen ASR/TTS realtime SDKs, pytest.

## Global Constraints

- ASR may connect before the user joins and before `scene.ready`.
- TTS should keep a long-lived WebSocket connection created during startup.
- Do not add LLM warmup in this iteration.
- Do not retry ASR or TTS in this design.
- Do not introduce BYO RTC, multi-user, multi-track, or multi-avatar behavior.
- Keep `_ready = True` gated until RTC readiness, ASR readiness, and TTS readiness have all completed.
- Preserve current cleanup behavior: if one startup branch fails, cancel/close the other initialized resources.

---

### Task 1: Add Long-Lived TTS Connection

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tts.py`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`

**Interfaces:**
- Produces: `async def QwenTts.connect(self) -> None`, used by `ChatPipeline.start()`.
- Preserves: `async def QwenTts.start(self) -> None`, called per response by `ChatPipeline._run_response()`.
- Preserves: `append_text(text)`, `finish()`, `cancel()`, `close()`, and `frames()` behavior.

- [ ] **Step 1: Write failing tests for TTS startup connection and provider reuse**

Add these tests to `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`:

```python
@pytest.mark.asyncio
async def test_connect_prepares_reusable_provider_without_starting_generation(tts, realtime):
    value, provider = tts

    await value.connect()

    assert provider.api_key == "key"
    realtime.connect.assert_called_once_with()
    realtime.update_session.assert_called_once_with(
        voice="Cherry", response_format="pcm24k", mode="server_commit"
    )
    assert value._generation == 0
    assert not value._active


@pytest.mark.asyncio
async def test_start_reuses_connected_provider_across_generations():
    realtime = FakeTts()
    provider = Provider(realtime)
    value = QwenTts(api_key="key", provider=provider)

    await value.connect()
    await value.start()
    first_callback = provider.callback
    first_generation = value._generation
    await value.finish()
    first_callback.on_event({"type": "response.done"})
    await asyncio.sleep(0)
    await value.start()

    assert len(provider.callbacks) == 1
    assert realtime.connect.call_count == 1
    assert realtime.close.call_count == 0
    assert provider.callback is first_callback
    assert value._generation == first_generation + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_tts.py::test_connect_prepares_reusable_provider_without_starting_generation tests/test_tts.py::test_start_reuses_connected_provider_across_generations -q
```

Expected: fail because `QwenTts.connect` does not exist or because `start()` still recreates the provider.

- [ ] **Step 3: Implement `QwenTts.connect()` and reuse connected providers**

In `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tts.py`:

Implement `connect()` as a thin lock wrapper around an internal `_connect_unlocked()` helper so `start()` can reuse the same setup without taking `_start_lock` recursively:

```python
    async def connect(self):
        async with self._start_lock:
            await self._connect_unlocked()

    async def _connect_unlocked(self):
        if self._closed:
            raise RuntimeError("QwenTts is closed")
        if self._connected_provider is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._provider_boundary.configure_api_key(self._api_key)
        self._callback = _Callback(self)
        provider = self._provider_boundary.create_realtime(
            callback=self._callback, **self._provider_kwargs
        )
        self._provider = provider

        def connect_and_configure():
            provider.connect()
            provider.update_session(
                voice=self._voice,
                response_format=self._provider_boundary.PCM_24000HZ_MONO_16BIT,
                mode="server_commit",
            )

        setup_task = asyncio.create_task(asyncio.to_thread(connect_and_configure))
        try:
            await asyncio.shield(setup_task)
        except BaseException:
            await asyncio.gather(setup_task, return_exceptions=True)
            try:
                await asyncio.to_thread(provider.close)
            except Exception:
                pass
            if self._provider is provider:
                self._provider = None
            if self._connected_provider is provider:
                self._connected_provider = None
            raise
        self._connected_provider = provider
```

Update `_Callback` so it reads the current owner generation instead of storing a fixed generation forever:

```python
class _Callback(QwenTtsRealtimeCallback):
    def __init__(self, owner):
        self._owner = owner

    def on_event(self, message):
        self._owner._receive_event(self._owner._generation, message)

    def on_close(self, code, message):
        error = None if code in (None, 1000) else RuntimeError(
            f"TTS provider closed ({code}): {message or 'unknown error'}"
        )
        self._owner._receive_terminal(self._owner._generation, error)
```

Update `start()` so it reuses an already connected provider without reconnecting:

```python
    async def start(self):
        async with self._start_lock:
            if self._closed:
                raise RuntimeError("QwenTts is closed")
            if self._active:
                raise RuntimeError("QwenTts is already active")
            if self._connected_provider is None:
                await self._connect_unlocked()
            self._loop = asyncio.get_running_loop()
            self._generation += 1
            self._active = True
            self._finished = False
            self._drain_queue()
```

Update existing tests whose old expectation was "fresh provider per generation":

- `test_cancelled_generation_cannot_leak_into_next_start` should assert late events from the same provider callback do not leak once `cancel()` advances generation.
- `test_terminal_then_start_uses_fresh_provider_and_callback` should become `test_terminal_then_start_reuses_provider_without_reconnect`.

- [ ] **Step 4: Run focused TTS tests**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_tts.py -q
```

Expected: all `test_tts.py` tests pass.

---

### Task 2: Fork/Join Pipeline Readiness

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/fakes.py`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Consumes: `QwenTts.connect() -> None` from Task 1.
- Produces: forked startup helpers inside `ChatPipeline`: `_wait_for_rtc_ready()`, `_connect_asr()`, and `_connect_tts()`.

- [ ] **Step 1: Extend `FakeTts` with `connect`**

In `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/fakes.py`, add:

```python
self.connect = AsyncMock()
```

to `FakeTts.__init__`.

- [ ] **Step 2: Write failing concurrency and readiness gate tests**

Add these tests to `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_start_forks_rtc_asr_and_tts_readiness(components, pipeline):
    session, asr, _, tts = components
    timeline = []
    release_rtc = asyncio.Event()
    release_asr = asyncio.Event()
    release_tts = asyncio.Event()

    async def wait_for_user():
        timeline.append("rtc:start")
        await release_rtc.wait()
        timeline.append("rtc:end")

    async def connect_asr():
        timeline.append("asr:start")
        await release_asr.wait()
        timeline.append("asr:end")

    async def connect_tts():
        timeline.append("tts:start")
        await release_tts.wait()
        timeline.append("tts:end")

    session.wait_for_user = wait_for_user
    session.wait_for_user_audio = AsyncMock()
    session.wait_for_scene_ready = AsyncMock()
    asr.connect.side_effect = connect_asr
    tts.connect.side_effect = connect_tts

    start = asyncio.create_task(pipeline.start())
    for _ in range(10):
        if {"rtc:start", "asr:start", "tts:start"}.issubset(timeline):
            break
        await asyncio.sleep(0)

    assert {"rtc:start", "asr:start", "tts:start"}.issubset(timeline)
    assert not pipeline._ready
    release_rtc.set()
    release_asr.set()
    assert not start.done()
    release_tts.set()
    await start
    assert pipeline._ready


@pytest.mark.asyncio
async def test_start_does_not_forward_audio_until_all_readiness_branches_join(
    components, pipeline
):
    session, asr, _, tts = components
    release_tts = asyncio.Event()

    async def connect_tts():
        await release_tts.wait()

    tts.connect.side_effect = connect_tts
    start = asyncio.create_task(pipeline.start())
    while "user_audio_frame" not in session.handlers:
        await asyncio.sleep(0)
    await session.emit("user_audio_frame", object())
    asr.feed_audio.assert_not_called()
    release_tts.set()
    await start
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_agent.py::test_start_forks_rtc_asr_and_tts_readiness tests/test_agent.py::test_start_does_not_forward_audio_until_all_readiness_branches_join -q
```

Expected: fail because `ChatPipeline.start()` still runs readiness sequentially and never calls `tts.connect()`.

- [ ] **Step 4: Implement fork/join startup**

In `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`, add helper methods to `ChatPipeline`:

```python
    async def _wait_for_rtc_ready(self):
        started = time.perf_counter()
        await self.session.wait_for_user()
        logger.info("User joined")
        await self.session.wait_for_user_audio()
        logger.info("User audio subscribed")
        await self.session.wait_for_scene_ready()
        logger.info("Scene ready")
        logger.info("RTC readiness completed in %.0f ms", (time.perf_counter() - started) * 1000)

    async def _connect_asr(self):
        started = time.perf_counter()
        await self.asr.connect()
        logger.info("ASR connected in %.0f ms", (time.perf_counter() - started) * 1000)

    async def _connect_tts(self):
        started = time.perf_counter()
        await self.tts.connect()
        logger.info("TTS connected in %.0f ms", (time.perf_counter() - started) * 1000)
```

Replace the sequential readiness body in `start()` with:

```python
            tasks = [
                asyncio.create_task(self._wait_for_rtc_ready(), name="rtc-ready"),
                asyncio.create_task(self._connect_asr(), name="asr-ready"),
                asyncio.create_task(self._connect_tts(), name="tts-ready"),
            ]
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            self._ready = True
            logger.info("Chat pipeline ready")
```

- [ ] **Step 5: Run focused agent tests**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_agent.py -q
```

Expected: all `test_agent.py` tests pass.

---

### Task 3: Full Regression and Handoff

**Files:**
- Verify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat`

**Interfaces:**
- Consumes completed Task 1 and Task 2 behavior.
- Produces verified rtc-chat demo state.

- [ ] **Step 1: Run full rtc-chat test suite**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Inspect diff**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
git diff -- agent.py tts.py tests/fakes.py tests/test_agent.py tests/test_tts.py
```

Expected: diff is limited to fork/join startup, TTS long-lived connection, and tests.

- [ ] **Step 3: Report results**

Report:

- files changed;
- exact test command and pass count;
- that LLM warmup was intentionally not added;
- that ASR/TTS now overlap RTC readiness and TTS is connected during startup.
