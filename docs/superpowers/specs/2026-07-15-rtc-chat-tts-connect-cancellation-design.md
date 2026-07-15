# RTC Chat TTS Connect Cancellation

## Context

RTC Chat starts a new DashScope realtime TTS provider for each response. A new
ASR final may interrupt the response while `provider.connect()` is running in
`asyncio.to_thread()`. Cancelling the awaiting coroutine does not stop that
thread. The current cleanup immediately calls `clear_appended_text()` against a
provider whose WebSocket is not established, producing `ConnectionError` and
occasionally leaving an old connection lifecycle running beside the next turn.

## Decision

Treat provider connection as an explicit asynchronous lifecycle:

- Run the blocking `connect()` call in its own task and await it through
  `asyncio.shield()` so cancellation does not cancel the task handle.
- Record connection state only after `connect()` and `update_session()` finish.
- If `start()` is cancelled, await the connection task to settle, close that
  provider, clear its state, and then re-raise `CancelledError`.
- `cancel()` sends `clear_appended_text()` only for a provider whose connection
  state is established. It still drains and terminates the current audio
  generation when the provider never connected.
- A later `start()` always uses a fresh provider and callback. Events from the
  cancelled generation remain ignored by the existing generation guard.

## Concurrency and Errors

`_start_lock` continues to serialize provider creation and replacement.
Connection cleanup is tied to the exact provider created by that `start()` so
it cannot close a newer generation. Provider close failures during cancellation
must not replace the original `CancelledError`; they may be logged for
diagnostics. Normal start failures remain visible to the response pipeline.

This change does not alter ASR/VAD sensitivity, barge-in policy, RTC session
lifecycle, or Data Channel behavior.

## Verification

- A deterministic test blocks provider `connect()`, cancels `start()`, then
  releases the connection and verifies the provider closes without calling
  `clear_appended_text()`.
- The cancelled `start()` raises `CancelledError` only after cleanup settles.
- A subsequent start uses a fresh provider and publishes PCM normally.
- Normal connected cancel still calls `clear_appended_text()` exactly once.
- The complete RTC Chat suite and compile check pass.
