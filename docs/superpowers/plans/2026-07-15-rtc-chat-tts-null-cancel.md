# RTC Chat TTS Null Cancel Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent response interruption during TTS connection setup from calling `clear_appended_text()` on a null provider.

**Architecture:** Preserve the existing TTS lifecycle and generation cleanup. Tighten the provider-state guard in `QwenTts.cancel()` so provider-specific cancellation occurs only for a non-null connected provider, and cover the exact interrupted-setup sequence with a regression test.

**Tech Stack:** Python 3.14, asyncio, pytest, DashScope realtime TTS

## Global Constraints

- The LiveKit `_data_track` startup error is out of scope.
- Do not change connected-provider cancellation behavior.
- The demo directory is not a Git repository, so implementation files cannot be committed there.

---

### Task 1: Guard cancellation after interrupted provider setup

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_tts.py`
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tts.py`

**Interfaces:**
- Consumes: `QwenTts.start() -> None` and `QwenTts.cancel() -> None`
- Produces: Idempotent `QwenTts.cancel()` behavior when both provider references were cleared by interrupted setup

- [ ] **Step 1: Extend the interrupted-connect regression test**

After the existing cancelled `start_task` assertions in `test_cancelled_connect_settles_and_closes_before_next_start`, invoke cancellation before starting the next generation:

```python
await value.cancel()
first.clear_appended_text.assert_not_called()
```

- [ ] **Step 2: Run the regression test and verify the current implementation fails**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_tts.py::test_cancelled_connect_settles_and_closes_before_next_start -v
```

Expected: FAIL with `AttributeError: 'NoneType' object has no attribute 'clear_appended_text'`.

- [ ] **Step 3: Implement the minimal non-null connected-provider guard**

Replace the provider-specific portion of `QwenTts.cancel()` with:

```python
provider = self._provider
if provider is not None and provider is self._connected_provider:
    await asyncio.to_thread(provider.clear_appended_text)
```

Keep generation cancellation, queue draining, and sentinel publication unchanged.

- [ ] **Step 4: Run the focused regression test**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_tts.py::test_cancelled_connect_settles_and_closes_before_next_start -v
```

Expected: `1 passed`.

- [ ] **Step 5: Run the TTS test module**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_tts.py -v
```

Expected: all TTS tests pass, including the existing connected-provider clear assertions.

- [ ] **Step 6: Run the complete RTC chat test suite**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q
```

Expected: all tests pass with no failures or errors.
