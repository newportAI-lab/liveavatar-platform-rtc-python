# RTC Chat Unexpected Disconnect Diagnostics

## Context

An RTC Chat session closed after roughly 144 seconds even though the user had
not requested disconnection and conversation traffic was active. The resulting
`SessionClosedError` is downstream evidence only. RTC Chat currently does not
log the SDK events that identify who left or why the LiveKit room disconnected.

The platform protocol may send `session.closing` with a reason such as
`timeout`. RTC Agent mode does not define an application-level keepalive; the
heartbeat described for WebSocket Agent mode does not justify adding one here.

## Decision

Add observation only. Do not change session lifetime, reconnect, keepalive,
error suppression, or TTS behavior in this change.

The backend pipeline will register handlers before readiness waits for:

- `session.closing`, logging its envelope data;
- `disconnected`, logging the LiveKit disconnect reason;
- `user_left`, `coordinator_left`, and `renderer_left`, logging the identity.

The browser will log the complete serializable `sdk:disconnected` payload rather
than only `info.reason`. It will retain the concise status message and add the
diagnostic payload to the page log.

## Data and Error Handling

Event handlers must not raise. Diagnostic values will be represented with
stable strings or JSON so logs remain useful when an SDK supplies an object,
string, or missing value. No credentials or tokens are logged.

The existing response failure remains visible. In particular,
`SessionClosedError` will not be reclassified until the new logs identify the
upstream cause.

## Verification

- Backend tests dispatch each SDK lifecycle event and assert the corresponding
  reason or identity is logged.
- Frontend source tests assert `sdk:disconnected` serializes the complete payload.
- The complete RTC Chat offline suite and compile check pass.
- A credentialed live retry records the lifecycle lines immediately before the
  next unexpected close. That live evidence determines whether a later fix
  belongs to the platform timeout policy, participant lifecycle, LiveKit
  connectivity, or client behavior.
