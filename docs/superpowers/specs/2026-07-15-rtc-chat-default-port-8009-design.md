# RTC Chat Default Port 8009

## Decision

Change the standalone RTC Chat demo's default HTTP port from `8080` to `8009`
because `8080` is frequently occupied in the development environment.

`HTTP_PORT` remains the supported override. No route, server lifecycle, or
network behavior changes.

## Scope

- `Settings.from_env()` defaults `HTTP_PORT` to `8009`.
- Quickstart commands and browser URLs use `http://localhost:8009`.
- Tests verify the new default and retain environment override coverage.

## Verification

Run the complete RTC Chat offline test suite and Python compile check. Starting
without `HTTP_PORT` must bind port `8009`; setting `HTTP_PORT` must continue to
select the supplied integer port.
