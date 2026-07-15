# RTC Chat Unexpected Disconnect Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the platform, participant, LiveKit, and browser evidence needed to identify why an active RTC Chat session closes unexpectedly.

**Architecture:** Register observation-only lifecycle handlers in `ChatPipeline.start()` before any readiness wait, and serialize the complete browser `sdk:disconnected` payload into the existing page log. The change does not alter session lifetime, reconnect behavior, keepalive, TTS, or exception classification.

**Tech Stack:** Python 3.11+, asyncio, LiveAvatar RTC SDK events, browser JavaScript, pytest

## Global Constraints

- Do not add an RTC Agent keepalive.
- Do not suppress or reclassify `SessionClosedError`.
- Do not change reconnect, disconnection, session lifetime, or TTS behavior.
- Do not log tokens, API keys, or credentials.
- Diagnostic event handlers must not raise.
- Preserve the concise browser disconnected status in addition to the complete diagnostic payload.

---

### Task 1: Log backend RTC lifecycle evidence

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Consumes: `Session.on(event: str)` handlers for `session.closing`, `disconnected`, `user_left`, `coordinator_left`, and `renderer_left`
- Produces: stable INFO/WARNING lifecycle log lines with the closing reason, disconnect reason, or participant identity

- [ ] **Step 1: Write a failing lifecycle logging test**

After `await pipeline.start()`, dispatch each event through `FakeSession.emit()` and assert these messages are present:

```python
await session.emit("session.closing", envelope)
await session.emit("disconnected", "DisconnectReason.STATE_MISMATCH")
await session.emit("user_left", "user")
await session.emit("coordinator_left", "coordinator_session")
await session.emit("renderer_left", "renderer_session")

assert "Session closing: reason=timeout" in messages
assert "RTC disconnected: reason=DisconnectReason.STATE_MISMATCH" in messages
assert "User left: identity=user" in messages
assert "Coordinator left: identity=coordinator_session" in messages
assert "Renderer left: identity=renderer_session" in messages
```

Use an envelope whose `data` is `{"reason": "timeout"}`. The handlers must tolerate a missing or non-dict `data` value by logging its safe string representation.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q tests/test_agent.py::test_pipeline_logs_session_and_participant_disconnect_evidence
```

Expected: FAIL because the handlers are not registered.

- [ ] **Step 3: Implement observation-only handlers**

Register handlers at the start of `ChatPipeline.start()`:

```python
@self.session.on("session.closing")
async def on_session_closing(envelope):
    data = getattr(envelope, "data", None)
    reason = data.get("reason") if isinstance(data, dict) else data
    logger.warning("Session closing: reason=%s", reason)

@self.session.on("disconnected")
async def on_disconnected(reason):
    logger.warning("RTC disconnected: reason=%s", reason)
```

Add equivalent non-raising INFO handlers for the three role-left events. Logging only is allowed; do not close or reconnect from these handlers.

- [ ] **Step 4: Run focused and complete backend tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_agent.py
.venv/bin/python -m pytest -q
```

Expected: the focused file and complete RTC Chat suite pass.

---

### Task 2: Log the complete browser disconnect payload

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/index.html`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_routes.py`

**Interfaces:**
- Consumes: browser SDK `sdk:disconnected` callback payload
- Produces: the existing concise disconnected status plus a JSON diagnostic line in the page log

- [ ] **Step 1: Write a failing frontend source test**

Extract the `sdk:disconnected` handler from `index.html` and assert it contains a guarded serialization call and diagnostic label:

```python
assert "JSON.stringify(info)" in disconnected
assert "Disconnect details:" in disconnected
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_routes.py::test_frontend_logs_complete_disconnect_payload
```

Expected: FAIL because only `info.reason` is currently logged.

- [ ] **Step 3: Add safe browser serialization**

Keep the existing status message and add:

```javascript
      try {
        addMessage('system', 'Disconnect details: ' + JSON.stringify(info || null));
      } catch (error) {
        addMessage('system', 'Disconnect details unavailable: ' + error.message);
      }
```

- [ ] **Step 4: Run complete tests and compile checks**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q agent.py asr.py llm.py tts.py tests
```

Expected: all tests pass and compileall exits without output.

---

### Task 3: Credentialed live evidence capture

**Files:**
- Observe: RTC Chat server and browser page logs

**Interfaces:**
- Consumes: Task 1 and Task 2 diagnostic log lines
- Produces: the first causal lifecycle event immediately preceding an unexpected close

- [ ] **Step 1: Restart and reproduce without manually disconnecting**

Run `python agent.py`, connect the browser, start the microphone, and continue active conversation past three minutes.

- [ ] **Step 2: Record the causal lines**

Capture all lines from 15 seconds before the close through the final disconnect. The evidence must include any available:

```text
Session closing: reason=...
RTC disconnected: reason=...
User left: identity=...
Coordinator left: identity=...
Renderer left: identity=...
Disconnect details: ...
```

- [ ] **Step 3: Classify without implementing a speculative fix**

Use the first causal event to route the next fix: platform timeout policy for `session.closing reason=timeout`, participant lifecycle for coordinator/renderer departure, LiveKit connectivity for a disconnect reason, or browser client behavior for an SDK-only disconnect. If none appears, add lower-level SDK logging in a separate design rather than guessing.
