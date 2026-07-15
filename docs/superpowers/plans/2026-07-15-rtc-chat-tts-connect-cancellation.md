# RTC Chat TTS Connect Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TTS response interruption safe while the DashScope realtime provider is still connecting.

**Architecture:** Execute provider connect and session configuration as one shielded background lifecycle task. Track established state for the exact provider generation, close a cancelled or failed provider before propagating the original result, and send provider-side clear only after establishment.

**Tech Stack:** Python 3.11+, asyncio, blocking DashScope realtime TTS client, pytest

## Global Constraints

- Cancelling `start()` must still propagate `asyncio.CancelledError`.
- A blocking provider lifecycle must settle and close before cancelled `start()` returns.
- `clear_appended_text()` must never run before provider connection and session configuration succeed.
- Normal connected `cancel()` must continue to clear provider text exactly once.
- A cancelled generation must not affect a later provider or callback.
- Do not change ASR/VAD, barge-in, RTC, or Data Channel behavior.

---

### Task 1: Reproduce the TTS connect cancellation race

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`

**Interfaces:**
- Consumes: `QwenTts.start()` and `QwenTts.cancel()`
- Produces: deterministic regression coverage for cancellation during blocking provider setup

- [ ] **Step 1: Add a blocking fake lifecycle test**

Use `threading.Event` objects to block `FakeTts.connect()` until the test releases it:

```python
connect_started = threading.Event()
release_connect = threading.Event()

def blocked_connect():
    connect_started.set()
    release_connect.wait(timeout=1)

first.connect.side_effect = blocked_connect
start_task = asyncio.create_task(value.start())
await asyncio.to_thread(connect_started.wait, 1)
start_task.cancel()
await asyncio.sleep(0)
assert not start_task.done()
release_connect.set()
with pytest.raises(asyncio.CancelledError):
    await start_task

first.clear_appended_text.assert_not_called()
first.close.assert_called_once_with()
```

Then call `await value.start()` with a second fake provider and assert the second provider connects and configures normally.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q tests/test_tts.py::test_cancelled_connect_settles_and_closes_before_next_start
```

Expected: FAIL because current `start()` returns cancellation before the blocking thread settles and current `cancel()` has no established-state guard.

---

### Task 2: Implement provider lifecycle ownership

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tts.py`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`

**Interfaces:**
- Consumes: the blocking provider methods `connect()`, `update_session()`, `clear_appended_text()`, and `close()`
- Produces: `QwenTts.start()`, `cancel()`, and `close()` with generation-safe connection state

- [ ] **Step 1: Track established state**

Initialize:

```python
self._connected_provider = None
```

Only assign the exact provider after both blocking setup methods finish.

- [ ] **Step 2: Run setup as one shielded task**

Capture the provider in a local variable and configure it in one thread function:

```python
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
    self._connected_provider = provider
except BaseException:
    self._active = False
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
```

The implementation may log close failure, but it must re-raise the original cancellation or setup exception.

- [ ] **Step 3: Guard provider-side cancellation and close state**

In `cancel()`, always terminate the local generation but call provider clear only when:

```python
if self._connected_provider is self._provider:
    await asyncio.to_thread(self._provider.clear_appended_text)
```

When replacing or closing a provider, clear `_connected_provider` only if it refers to that exact provider.

- [ ] **Step 4: Run focused and complete TTS tests**

```bash
.venv/bin/python -m pytest -q tests/test_tts.py::test_cancelled_connect_settles_and_closes_before_next_start
.venv/bin/python -m pytest -q tests/test_tts.py
```

Expected: the regression and all existing normal cancel, restart, callback, and non-blocking lifecycle tests pass.

---

### Task 3: Complete RTC Chat verification

**Files:**
- Verify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat`

**Interfaces:**
- Consumes: Tasks 1 and 2
- Produces: verified demo behavior ready for credentialed retry

- [ ] **Step 1: Run the complete offline suite and compile check**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q agent.py asr.py llm.py tts.py tests
```

Expected: all tests pass and compileall exits without output.

- [ ] **Step 2: Retry rapid barge-in with credentials**

Restart `python agent.py`, connect and start the microphone, then speak a short utterance followed quickly by another while the first response logs `Response started`. Verify there is no `Failed to cancel TTS`, provider `ConnectionError`, or delayed `websocket error: Connection timed out`, and that the second response reaches `TTS PCM publication started`.
