# RTC Data Channel Without Topic

## Context

The RTC Agent protocol, platform implementation, and browser SDK do not define a
LiveKit Data Channel topic. The browser SDK publishes system events such as
`scene.ready` without a topic. The Python RTC SDK introduced a `liveavatar`
topic independently, causing valid browser events to be discarded.

## Decision

The RTC Python SDK will not assign protocol meaning to LiveKit topics:

- Outbound data uses `publish_data(..., reliable=True)` without a topic.
- Inbound data is not filtered by topic.
- The JSON envelope remains the protocol boundary. It must contain a string
  `event`, and known event fields continue to receive strict validation.
- `DataChannelEvent.topic` remains optional diagnostic metadata so applications
  can observe a topic supplied by a participant, but SDK behavior does not
  depend on it.

This is an intentional breaking correction to align the SDK with the existing
platform protocol. No compatibility configuration or topic switch is added.

## Data Flow

The browser, RTC agent, coordinator, and renderer publish protocol envelopes as
reliable LiveKit data packets without setting a topic. Receivers parse and
validate the envelope, then dispatch by `event`. For example, a topicless
`{"event":"scene.ready"}` packet sets the session scene-ready state and releases
`wait_for_scene_ready()`.

## Error Handling

Malformed JSON, a non-object envelope, a missing or non-string `event`, and
invalid known-event fields dispatch `protocol_error`. A non-empty topic neither
validates nor invalidates a packet; it is recorded only as metadata.

## Verification

- Sending helpers are tested to call LiveKit without a topic argument.
- Topicless `scene.ready` is dispatched and releases the session waiter.
- A valid envelope with an arbitrary topic is also dispatched, proving topics
  are not protocol filters.
- Existing malformed-envelope tests remain unchanged.
- The complete SDK and RTC Chat offline suites pass after reinstalling the local
  SDK into the demo virtual environment.

## Related Demo Cleanup

RTC Chat will stop reporting a readiness-task exception a second time as
`Session cleanup failed`. The original `RTC readiness pipeline failed` traceback
remains the authoritative error, while actual pipeline and client cleanup
failures continue to be logged.
