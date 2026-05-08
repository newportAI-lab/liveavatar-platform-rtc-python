from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from .event_dispatcher import Callback, EventDispatcher
from .livekit_manager import LiveKitManager
from .types import AudioFrame, AudioTrackInfo, TTSConfig

# Event name constants — matches PROTOCOL.livekit.md
# Inbound (user/coordinator → agent via Data Channel)
INPUT_TEXT = "input.text"
SCENE_READY = "scene.ready"
SESSION_STATE = "session.state"
SESSION_CLOSING = "session.closing"
IDLE_TRIGGER = "system.idleTrigger"
ERROR = "error"
# SDK-level events (LiveKit tracks)
USER_AUDIO_FRAME = "user_audio_frame"
USER_AUDIO_TRACK_SUBSCRIBED = "user_audio_track_subscribed"
DISCONNECTED = "disconnected"
USER_JOINED = "user_joined"


class Session:
    """Active Platform RTC session — the developer's interface to the digital human."""

    def __init__(self, lk_manager: LiveKitManager) -> None:
        self._lk = lk_manager
        self.session_id = lk_manager.session_id
        self._events = EventDispatcher()
        self._setup_bridge()

    # ── Event Registration ──────────────────────────────────

    def on(self, event: str) -> Callable[[Callback], Callback]:
        """Decorator: register a callback for a Live Avatar event.

        Usage:
            @session.on("input.text")
            async def handle_text(data: dict): ...
        """
        return self._events.on(event)

    def _setup_bridge(self) -> None:
        lk_events = self._lk.events

        lk_events.add(
            "user_audio_frame",
            lambda frame: self._events.dispatch(USER_AUDIO_FRAME, frame),
        )
        lk_events.add(
            "user_audio_track_subscribed",
            lambda info: self._events.dispatch(USER_AUDIO_TRACK_SUBSCRIBED, info),
        )
        lk_events.add(
            "user_joined",
            lambda identity: self._events.dispatch(USER_JOINED, identity),
        )
        lk_events.add(
            "disconnected",
            lambda reason: self._events.dispatch(DISCONNECTED, reason),
        )

        # Data Channel events — agent receives these from user/coordinator
        for event in (
            INPUT_TEXT,
            SCENE_READY,
            SESSION_STATE,
            SESSION_CLOSING,
            IDLE_TRIGGER,
            ERROR,
        ):
            lk_events.add(event, self._make_data_handler(event))

    def _make_data_handler(self, event: str):
        async def handle(data: dict) -> None:
            await self._events.dispatch(event, data)
        return handle

    # ── TTS Output ──────────────────────────────────────────

    async def publish_audio(self, frame: AudioFrame) -> None:
        """Publish an audio frame to the agent Audio Track for developer-provided TTS."""
        await self._lk.publish_audio_frame(frame)

    # ── Platform TTS (response.*) ───────────────────────────

    async def send_response_start(self, config: TTSConfig | None = None) -> str:
        """Begin a platform-TTS response. Returns a request_id."""
        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {"requestId": request_id}
        if config:
            if config.speed is not None:
                payload["speed"] = config.speed
            if config.volume is not None:
                payload["volume"] = config.volume
            if config.mood is not None:
                payload["mood"] = config.mood
        await self._lk.send_data("response.start", payload)
        return request_id

    async def send_response_chunk(self, request_id: str, text: str) -> None:
        """Send a chunk of platform-TTS text."""
        await self._lk.send_data("response.chunk", {"requestId": request_id, "text": text})

    async def send_response_done(self, request_id: str) -> None:
        """Mark the platform-TTS response as complete."""
        await self._lk.send_data("response.done", {"requestId": request_id})

    async def send_response_cancel(self, request_id: str) -> None:
        """Cancel an in-progress platform-TTS response."""
        await self._lk.send_data("response.cancel", {"requestId": request_id})

    # ── Developer TTS Audio Lifecycle (response.audio.*) ────
    # Bracket publish_audio() calls so the coordinator can track audio state.
    # Use start/finish for normal conversation replies.
    # Use promptStart/promptFinish for proactive/idle-prompt speech.

    async def send_response_audio_start(self) -> str:
        """Begin developer TTS audio for a normal conversation reply."""
        request_id = str(uuid.uuid4())
        await self._lk.send_data("response.audio.start", {"requestId": request_id})
        return request_id

    async def send_response_audio_finish(self, request_id: str) -> None:
        """End developer TTS audio for a normal conversation reply."""
        await self._lk.send_data("response.audio.finish", {"requestId": request_id})

    async def send_response_audio_prompt_start(self) -> str:
        """Begin developer TTS audio for a proactive/idle-prompt speech."""
        request_id = str(uuid.uuid4())
        await self._lk.send_data("response.audio.promptStart", {"requestId": request_id})
        return request_id

    async def send_response_audio_prompt_finish(self, request_id: str) -> None:
        """End developer TTS audio for a proactive/idle-prompt speech."""
        await self._lk.send_data("response.audio.promptFinish", {"requestId": request_id})

    # ── Subtitle / Caption (response.chunk for frontend) ────

    async def send_subtitle(self, request_id: str, text: str) -> None:
        """Send subtitle text to the frontend via response.chunk."""
        await self._lk.send_data("response.chunk", {"requestId": request_id, "text": text})

    # ── Developer ASR (input.asr.*) ─────────────────────────

    async def send_asr_partial(self, text: str) -> None:
        """Send a partial ASR result to the frontend for live captions."""
        await self._lk.send_data("input.asr.partial", {"text": text})

    async def send_asr_final(self, text: str) -> None:
        """Send a final ASR result to the frontend and coordinator."""
        await self._lk.send_data("input.asr.final", {"text": text})

    # ── Developer VAD (input.voice.*) ───────────────────────
    # REQUIRED when using developer ASR. The coordinator uses these
    # boundaries to drive LISTENING ↔ THINKING ↔ SPEAKING transitions.

    async def send_voice_start(self) -> None:
        """Signal that user voice activity started (VAD start)."""
        await self._lk.send_data("input.voice.start")

    async def send_voice_finish(self) -> None:
        """Signal that user voice activity ended (VAD end)."""
        await self._lk.send_data("input.voice.finish")

    # ── Control ─────────────────────────────────────────────

    async def interrupt(self) -> None:
        """Interrupt current avatar speech."""
        await self._lk.send_data("control.interrupt")

    async def send_prompt(self, text: str) -> None:
        """Trigger proactive avatar speech (idle prompt)."""
        await self._lk.send_data("system.prompt", {"text": text})

    # ── Error Reporting ─────────────────────────────────────

    async def send_error(self, code: str, message: str) -> None:
        """Report a developer-side error to the coordinator."""
        await self._lk.send_data("error", {"code": code, "message": message})

    # ── Lifecycle ───────────────────────────────────────────

    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        await self._lk.wait_until_ready(timeout)

    async def close(self) -> None:
        """Leave LiveKit room and release resources."""
        await self._lk.disconnect()
