from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable

from .errors import (
    AudioFormatError,
    AudioPublishError,
    SessionClosedError,
    SessionWaitTimeoutError,
)
from .event_dispatcher import Callback, EventDispatcher
from .livekit_manager import LiveKitManager
from .types import AudioFrame, DataChannelEvent, FrontendConnection

SCENE_READY = "scene.ready"
SESSION_STATE = "session.state"
SESSION_CLOSING = "session.closing"
IDLE_TRIGGER = "system.idleTrigger"
ERROR = "error"
CUSTOM_EVENT = "custom_event"

USER_AUDIO_FRAME = "user_audio_frame"
USER_AUDIO_TRACK_SUBSCRIBED = "user_audio_track_subscribed"
USER_AUDIO_TRACK_UNSUBSCRIBED = "user_audio_track_unsubscribed"
USER_JOINED = "user_joined"
USER_LEFT = "user_left"
DISCONNECTED = "disconnected"

_KNOWN_DATA_EVENTS = {
    SCENE_READY,
    SESSION_STATE,
    SESSION_CLOSING,
    IDLE_TRIGGER,
    ERROR,
}


class Session:
    """An active RTC Agent session."""

    def __init__(self, lk_manager: LiveKitManager) -> None:
        self._lk = lk_manager
        self.session_id = lk_manager.session_id
        self.sfu_url = lk_manager.sfu_url
        self.user_token = lk_manager.user_token
        self.frontend_connection = FrontendConnection(
            user_token=lk_manager.user_token,
            sfu_url=lk_manager.sfu_url,
        )
        self._events = EventDispatcher()

        self._agent_connected = True
        self._user_joined = False
        self._scene_ready = False
        self._user_audio_subscribed = False
        self._closing = False
        self._closed = False
        self._output_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

        self._user_event = asyncio.Event()
        self._scene_ready_event = asyncio.Event()
        self._user_audio_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._setup_bridge()

    @property
    def is_agent_connected(self) -> bool:
        return self._agent_connected

    @property
    def is_user_joined(self) -> bool:
        return self._user_joined

    @property
    def is_scene_ready(self) -> bool:
        return self._scene_ready

    @property
    def is_user_audio_subscribed(self) -> bool:
        return self._user_audio_subscribed

    @property
    def is_closing(self) -> bool:
        return self._closing

    @property
    def is_closed(self) -> bool:
        return self._closed

    def on(self, event: str) -> Callable[[Callback], Callback]:
        return self._events.on(event)

    def _setup_bridge(self) -> None:
        events = self._lk.events
        events.add(USER_JOINED, self._on_user_joined)
        events.add(USER_LEFT, self._on_user_left)
        events.add(USER_AUDIO_TRACK_SUBSCRIBED, self._on_user_audio_subscribed)
        events.add(USER_AUDIO_TRACK_UNSUBSCRIBED, self._on_user_audio_unsubscribed)
        events.add(USER_AUDIO_FRAME, self._forward(USER_AUDIO_FRAME))
        events.add("user_audio_track_muted", self._forward("user_audio_track_muted"))
        events.add("user_audio_track_unmuted", self._forward("user_audio_track_unmuted"))
        events.add("coordinator_joined", self._forward("coordinator_joined"))
        events.add("coordinator_left", self._forward("coordinator_left"))
        events.add("renderer_joined", self._forward("renderer_joined"))
        events.add("renderer_left", self._forward("renderer_left"))
        events.add("connection_quality_changed", self._forward("connection_quality_changed"))
        events.add("reconnecting", self._forward("reconnecting"))
        events.add("reconnected", self._forward("reconnected"))
        events.add("data_channel_event", self._on_data_channel_event)
        events.add(DISCONNECTED, self._on_disconnected)

    def _forward(self, event: str) -> Callback:
        async def forward(*args: object) -> None:
            await self._events.dispatch(event, *args)

        return forward

    async def _on_user_joined(self, identity: str) -> None:
        self._user_joined = True
        self._user_event.set()
        await self._events.dispatch(USER_JOINED, identity)

    async def _on_user_left(self, identity: str) -> None:
        self._user_joined = False
        self._user_event.clear()
        self._user_audio_subscribed = False
        self._user_audio_event.clear()
        await self._events.dispatch(USER_LEFT, identity)

    async def _on_user_audio_subscribed(self, info: object) -> None:
        self._user_audio_subscribed = True
        self._user_audio_event.set()
        await self._events.dispatch(USER_AUDIO_TRACK_SUBSCRIBED, info)

    async def _on_user_audio_unsubscribed(self, track_sid: str) -> None:
        self._user_audio_subscribed = False
        self._user_audio_event.clear()
        await self._events.dispatch(USER_AUDIO_TRACK_UNSUBSCRIBED, track_sid)

    async def _on_data_channel_event(self, envelope: DataChannelEvent) -> None:
        if envelope.event == SCENE_READY:
            if self._scene_ready:
                return
            self._scene_ready = True
            self._scene_ready_event.set()
        elif envelope.event == SESSION_CLOSING:
            self._closing = True

        event = envelope.event if envelope.event in _KNOWN_DATA_EVENTS else CUSTOM_EVENT
        await self._events.dispatch(event, envelope)

    async def _on_disconnected(self, reason: str) -> None:
        self._mark_closed()
        await self._events.dispatch(DISCONNECTED, reason)

    def _mark_closed(self) -> None:
        self._closing = True
        self._closed = True
        self._agent_connected = False
        self._closed_event.set()

    async def _wait_for(
        self, event: asyncio.Event, name: str, timeout: float
    ) -> None:
        if self._closed:
            raise SessionClosedError(f"session {self.session_id} is closed")
        if event.is_set():
            return

        event_task = asyncio.create_task(event.wait())
        close_task = asyncio.create_task(self._closed_event.wait())
        done, pending = await asyncio.wait(
            {event_task, close_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if close_task in done:
            raise SessionClosedError(
                f"session {self.session_id} closed while waiting for {name}"
            )
        if event_task not in done:
            raise SessionWaitTimeoutError(f"timed out waiting for {name}")

    async def wait_for_user(self, timeout: float = 30.0) -> None:
        await self._wait_for(self._user_event, "user", timeout)

    async def wait_for_user_audio(self, timeout: float = 30.0) -> None:
        await self._wait_for(self._user_audio_event, "user_audio", timeout)

    async def wait_for_scene_ready(self, timeout: float = 30.0) -> None:
        await self._wait_for(self._scene_ready_event, "scene_ready", timeout)

    async def publish_audio(self, frame: AudioFrame) -> None:
        self._ensure_open()
        await self._lk.publish_audio_frame(frame)

    def _ensure_open(self) -> None:
        if self._closing or self._closed:
            raise SessionClosedError(f"session {self.session_id} is closed")

    async def publish_audio_stream(
        self, frames: AsyncIterable[AudioFrame]
    ) -> None:
        self._ensure_open()
        if self._output_task is not None and not self._output_task.done():
            raise AudioPublishError("an audio stream is already active")

        async def publish() -> None:
            async for frame in frames:
                self._ensure_open()
                await self.publish_audio(frame)

        output_task = asyncio.create_task(publish())
        self._output_task = output_task
        try:
            await output_task
        except asyncio.CancelledError:
            raise
        except (AudioFormatError, SessionClosedError):
            raise
        except Exception as exc:
            error = AudioPublishError("failed to publish audio stream")
            await self._events.dispatch(ERROR, error)
            raise error from exc
        finally:
            if self._output_task is output_task:
                self._output_task = None

    async def send_custom_event(
        self,
        event: str,
        data: dict | None = None,
        request_id: str | None = None,
        response_id: str | None = None,
        seq: int | None = None,
        timestamp: int | None = None,
    ) -> None:
        await self._lk.send_data_event(
            DataChannelEvent(
                event=event,
                data=data or {},
                request_id=request_id,
                response_id=response_id,
                seq=seq,
                timestamp=timestamp,
            )
        )

    async def interrupt(self, request_id: str | None = None) -> None:
        self._ensure_open()
        task = self._output_task
        if task is not None:
            if not task.done():
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
        await self._lk.clear_output_queue()
        await self._lk.send_data_event(
            DataChannelEvent(event="control.interrupt", request_id=request_id)
        )
        await self._events.dispatch("interrupted", request_id)

    async def send_voice_start(self, request_id: str) -> None:
        await self.send_custom_event("input.voice.start", request_id=request_id)

    async def send_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        await self.send_custom_event(
            "input.asr.partial", {"text": text}, request_id=request_id, seq=seq
        )

    async def send_voice_finish(self, request_id: str) -> None:
        await self.send_custom_event("input.voice.finish", request_id=request_id)

    async def send_asr_final(self, request_id: str, text: str) -> None:
        await self.send_custom_event(
            "input.asr.final", {"text": text}, request_id=request_id
        )

    async def send_subtitle(
        self,
        request_id: str,
        response_id: str,
        text: str,
        seq: int,
        timestamp: int,
    ) -> None:
        await self.send_custom_event(
            "response.chunk",
            {"text": text},
            request_id=request_id,
            response_id=response_id,
            seq=seq,
            timestamp=timestamp,
        )

    async def close(self) -> None:
        task = self._close_task
        if task is not None:
            if task is asyncio.current_task():
                return
            await asyncio.shield(task)
            return
        if self._closed:
            return
        self._closing = True
        self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        task = self._output_task
        if task is not None and not task.done():
            task.cancel()
        try:
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await self._lk.disconnect()
        finally:
            self._mark_closed()
            await self._events.dispatch("closed")
