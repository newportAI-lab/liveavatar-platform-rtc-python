# RTC Chat Text Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make rtc-chat text input support explicit through tests and documentation while preserving the audio-only RTC platform contract.

**Architecture:** The existing frontend sends `client.sendTextQuestion(text)`, and the backend consumes `input.text` custom events via `ChatPipeline.on_text_input()`. This plan strengthens coverage and docs without changing UI copy or adding a platform text protocol.

**Tech Stack:** Python 3.14, asyncio, pytest, static HTML/JS demo, LiveAvatar RTC browser SDK.

## Global Constraints

- Do not change UI copy or input placeholder text.
- Do not add a platform-side text-driving protocol.
- Do not change the RTC SDK browser API.
- Do not change ASR behavior for voice turns.
- Text input is handled by the agent and converted to TTS audio.
- The RTC platform still receives audio output only.

---

### Task 1: Test Text Input as Agent Turn

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_agent.py`

**Interfaces:**
- Consumes: `ChatPipeline.on_text_input(text, request_id=None)`.
- Consumes: RTC custom event handler registered for `input.text`.
- Produces: stronger regression coverage for text -> LLM -> TTS -> RTC audio.

- [ ] **Step 1: Add a focused text-turn test**

Add this test near the existing text input tests in `tests/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_text_input_skips_asr_events_and_publishes_tts_audio(
    components, pipeline
):
    session, _, _, tts = components
    await pipeline.start()

    await session.emit(
        "custom_event",
        type(
            "Envelope",
            (),
            {
                "event": "input.text",
                "data": {"text": "文字问题"},
                "request_id": "text-request",
            },
        )(),
    )

    session.send_voice_start.assert_not_awaited()
    session.send_voice_finish.assert_not_awaited()
    session.send_asr_partial.assert_not_awaited()
    session.send_asr_final.assert_not_awaited()
    session.publish_audio_stream.assert_awaited_once()
    tts.start.assert_awaited_once()
    tts.finish.assert_awaited_once()
    assert pipeline.conversation[-2:] == [
        {"role": "user", "text": "文字问题"},
        {"role": "agent", "text": "晴天"},
    ]
```

- [ ] **Step 2: Run the focused test**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_agent.py::test_text_input_skips_asr_events_and_publishes_tts_audio -q
```

Expected: pass if existing behavior already meets the design. If it fails, make the smallest backend change needed to preserve this contract.

- [ ] **Step 3: Run agent tests**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest tests/test_agent.py -q
```

Expected: all `test_agent.py` tests pass.

---

### Task 2: Document Text Input Semantics

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/QUICKSTART.md`

**Interfaces:**
- Produces: user-facing documentation for text and voice input in RTC mode.

- [ ] **Step 1: Add documentation without changing UI copy**

Update `QUICKSTART.md` to state that users may type or speak, but the digital human platform still receives only agent-published audio. Use this exact sentence in the usage section:

```markdown
The demo supports both microphone input and typed text input. Typed text is sent to the agent as a user turn, then the agent replies through LLM -> TTS -> RTC audio publication, so the digital human platform still receives audio output only.
```

- [ ] **Step 2: Check the documentation diff**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
rg -n "typed text|microphone input|audio output only" QUICKSTART.md
```

Expected: the new documentation sentence appears once.

---

### Task 3: Full Regression

**Files:**
- Verify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat`

**Interfaces:**
- Consumes all completed changes.
- Produces verified demo state.

- [ ] **Step 1: Run full suite**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q
```

Expected: all tests pass. If sandbox socket binding fails for `aiohttp` route tests, rerun the same command with permission to bind local loopback sockets.

- [ ] **Step 2: Report outcome**

Report changed files, exact verification result, and that UI copy was not changed.
