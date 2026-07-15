# RTC Chat Default Port 8009 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the standalone RTC Chat demo listen on port `8009` by default while preserving the `HTTP_PORT` override.

**Architecture:** Change only the environment default in `Settings.from_env()`. Keep the aiohttp runner and all routes unchanged, and update the quickstart URLs and tests to match.

**Tech Stack:** Python 3.11+, aiohttp, pytest, Markdown

## Global Constraints

- Default `HTTP_PORT` must be `8009`.
- An explicitly supplied `HTTP_PORT` must continue to override the default.
- Do not change routes, server lifecycle, or networking behavior.
- Quickstart browser URLs and example configuration must use port `8009`.

---

### Task 1: Change and verify the RTC Chat default port

**Files:**
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/agent.py`
- Modify: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/QUICKSTART.md`
- Test: `/Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat/tests/test_routes.py`

**Interfaces:**
- Consumes: `Settings.from_env()` and the `HTTP_PORT` environment variable
- Produces: `Settings.http_port == 8009` when unset and the supplied integer when set

- [ ] **Step 1: Write failing default and override tests**

```python
def test_http_port_defaults_to_8009(monkeypatch):
    monkeypatch.delenv("HTTP_PORT", raising=False)
    assert Settings.from_env().http_port == 8009


def test_http_port_environment_override_is_preserved(monkeypatch):
    monkeypatch.setenv("HTTP_PORT", "9010")
    assert Settings.from_env().http_port == 9010
```

The existing test environment may leave credential variables unset because `Settings.from_env()` constructs settings without validating them.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd /Users/luffer/workspace/liveavatar-ws-integration-demo/python-agent/rtc-chat
.venv/bin/python -m pytest -q \
  tests/test_routes.py::test_http_port_defaults_to_8009 \
  tests/test_routes.py::test_http_port_environment_override_is_preserved
```

Expected: the default test fails with `8080 != 8009`; the override test passes.

- [ ] **Step 3: Change the environment default**

In `Settings.from_env()` use:

```python
http_port=int(os.getenv("HTTP_PORT", "8009")),
```

- [ ] **Step 4: Update quickstart references**

Replace the default example and browser URL:

```bash
export HTTP_PORT="8009"
```

```markdown
Open `http://localhost:8009` (or the port selected by `HTTP_PORT`).
```

Update the credentialed live smoke URL to `http://localhost:8009` as well. Do not change unrelated occurrences of numbers.

- [ ] **Step 5: Run complete verification**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q agent.py asr.py llm.py tts.py tests
rg -n "8080|8009|HTTP_PORT" agent.py QUICKSTART.md tests
```

Expected: all tests pass, compileall exits without output, no default URL or configuration still uses `8080`, and the only default port is `8009`.
