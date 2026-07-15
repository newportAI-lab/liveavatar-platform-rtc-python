# RTC Data Channel Without Topic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align RTC Agent Data Channel behavior with the existing platform and browser SDK by removing topic semantics while preserving strict envelope validation.

**Architecture:** `LiveKitManager` will publish reliable packets without a topic and will parse every received data packet regardless of topic. `DataChannelEvent.topic` remains optional observation metadata. RTC Chat will continue waiting for `scene.ready`, and its cleanup logger will report only actual cleanup failures rather than repeating the readiness exception.

**Tech Stack:** Python 3.10+, asyncio, LiveKit Python SDK, pytest, aiohttp

## Global Constraints

- Do not add a topic configuration or compatibility switch.
- Do not use a LiveKit topic for outbound RTC Agent protocol messages.
- Do not filter inbound RTC Agent protocol messages by LiveKit topic.
- Keep strict JSON envelope validation and known-event field validation.
- Keep `DataChannelEvent.topic: str | None` as diagnostic metadata only.
- Preserve unrelated user changes and the untracked `.codegraph/` and `ragflow/` trees.

---

### Task 1: Remove topic semantics from RTC SDK data transport

**Files:**
- Modify: `src/liveavatar_rtc/livekit_manager.py`
- Test: `tests/test_livekit_manager.py`

**Interfaces:**
- Consumes: `LiveKitManager.send_data(event: str, data: dict | None)` and `send_data_event(event: DataChannelEvent)`
- Produces: reliable topicless LiveKit data packets and topic-independent inbound `DataChannelEvent` dispatch

- [ ] **Step 1: Update the failing outbound and inbound tests**

Assert both sending helpers omit `topic`, assert topicless `scene.ready` dispatches, and replace the old “other topic is ignored” assertion with a valid arbitrary-topic packet that dispatches while retaining its topic as metadata.

```python
assert publish.await_args.kwargs == {"reliable": True}

await manager._on_data_received(packet_with_topic("custom-observer-topic"))
event = handler.await_args.args[0]
assert event.event == "scene.ready"
assert event.topic == "custom-observer-topic"
```

- [ ] **Step 2: Run focused tests and verify the old behavior fails**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_livekit_manager.py::TestSendData \
  tests/test_livekit_manager.py::TestDataChannelEvents
```

Expected: outbound assertions fail because `topic="liveavatar"` is present, and the arbitrary-topic receive assertion fails because the packet is filtered.

- [ ] **Step 3: Implement topicless transport**

Remove `DATA_TOPIC`, publish without `topic`, and remove the early topic filter:

```python
await self._room.local_participant.publish_data(payload, reliable=True)

async def _on_data_received(self, packet: rtc.DataPacket) -> None:
    try:
        message = json.loads(packet.data)
```

Continue assigning `topic=packet.topic` when constructing `DataChannelEvent`.

- [ ] **Step 4: Run focused and complete SDK tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_livekit_manager.py
.venv/bin/python -m pytest -q tests
```

Expected: all tests pass; the complete suite reports at least 161 passing tests.

- [ ] **Step 5: Commit the SDK transport change**

```bash
git add src/liveavatar_rtc/livekit_manager.py tests/test_livekit_manager.py
git commit -m "fix: remove rtc data channel topic semantics"
```

---

### Task 2: Document the topicless protocol behavior

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 transport behavior
- Produces: public SDK documentation stating that event envelopes, not topics, define protocol messages

- [ ] **Step 1: Add a documentation assertion**

Run after editing:

```bash
rg -n "topic|Data Channel" README.md
```

Expected: README states that the SDK neither sets nor filters by a LiveKit topic and that `DataChannelEvent.topic` is diagnostic metadata.

- [ ] **Step 2: Update the Data Channel section**

Add this behavior description without changing unrelated examples:

```markdown
RTC Agent protocol packets are reliable LiveKit Data Channel messages without a
required topic. The SDK dispatches by the JSON `event` field and does not filter
incoming packets by topic. `DataChannelEvent.topic` is retained only for
diagnostics when a participant supplies one.
```

- [ ] **Step 3: Verify documentation and commit**

```bash
git diff --check -- README.md
git add README.md
git commit -m "docs: document topicless rtc data events"
```

Expected: both commands exit successfully.

---

### Task 3: Finalize RTC Chat readiness cleanup and deploy the local SDK

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`
- Runtime environment: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/.venv`

**Interfaces:**
- Consumes: topic-independent `scene.ready` handling from Task 1
- Produces: one authoritative readiness traceback and a demo environment containing the corrected SDK

- [ ] **Step 1: Verify the duplicate-log regression test fails against old cleanup aggregation**

The test creates a completed readiness task that raises, calls `Runtime.stop()`, and asserts `logger.error` is not called with `Session cleanup failed` for that readiness result.

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_agent.py::test_runtime_stop_does_not_report_readiness_error_as_cleanup_failure
```

Expected before the fix: FAIL with one `Session cleanup failed: readiness failed` call.

- [ ] **Step 2: Retrieve but do not aggregate the readiness result**

```python
if task is not None:
    await asyncio.gather(task, return_exceptions=True)
```

Keep pipeline and client results in the cleanup-error list so their failures are still logged.

- [ ] **Step 3: Reinstall the local SDK and run the complete demo suite**

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pip install --no-deps --force-reinstall \
  /Users/luffer/workspace/liveavatar-platform-rtc-python
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q agent.py asr.py llm.py tts.py tests
```

Expected: installation succeeds, at least 81 tests pass, and compileall exits with no output.

- [ ] **Step 4: Verify the installed SDK and perform a live retry**

```bash
.venv/bin/python -c 'import inspect; from liveavatar_rtc.livekit_manager import LiveKitManager; s=inspect.getsource(LiveKitManager._on_data_received); assert "packet.topic" not in s.split("try:", 1)[0]'
```

Expected: command exits successfully. Restart `python agent.py`, connect the browser, publish the microphone track within 30 seconds, and verify logs reach `Scene ready` followed by `ASR connected`. Record the credentialed live retry separately from offline verification.

