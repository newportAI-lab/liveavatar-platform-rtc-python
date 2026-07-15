# RTC Chat TTS Null Cancel Fix

## Scope

Fix the `Failed to cancel TTS` error that occurs when a response is interrupted while the TTS provider is still connecting. The unrelated LiveKit `_data_track` startup error is explicitly out of scope.

## Root cause

`QwenTts.start()` clears both `_provider` and `_connected_provider` when its setup task is cancelled. The response cleanup subsequently calls `QwenTts.cancel()`. Its identity check treats `None is None` as a connected provider and then calls `clear_appended_text()` on `None`.

## Design

`QwenTts.cancel()` will capture the current provider and call `clear_appended_text()` only when that provider is non-null and is the connected provider. Connected providers keep the existing cancellation behavior; cancelled or failed setup remains a no-op at the provider boundary while still draining the audio queue and terminating the generation.

## Verification

Extend the cancelled-connect regression test so it invokes `cancel()` after the interrupted `start()`. The test must prove that no provider clear is attempted. Run the complete `rtc-chat` test suite afterward to guard normal TTS interruption and response behavior.
