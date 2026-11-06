from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, Awaitable, Callable

from .errors import PromptStreamClosedError
from .types import AudioFrame, DataChannelEvent, ResponseStateEvent

SendEvent = Callable[[DataChannelEvent], Awaitable[None]]
SendAudio = Callable[[AudioFrame], Awaitable[None]]
SendAudioStream = Callable[[AsyncIterable[AudioFrame]], Awaitable[None]]


class ResponseHandle:
    """Tracks the first platform terminal state for one response."""

    def __init__(self, request_id: str, response_id: str) -> None:
        self.request_id = request_id
        self.response_id = response_id
        self._terminal: ResponseStateEvent | None = None
        self._terminal_future: asyncio.Future[ResponseStateEvent] = (
            asyncio.get_running_loop().create_future()
        )

    @property
    def terminal(self) -> ResponseStateEvent | None:
        return self._terminal

    async def wait_terminal(self, timeout: float | None = None) -> ResponseStateEvent:
        waiter = asyncio.shield(self._terminal_future)
        if timeout is None:
            return await waiter
        return await asyncio.wait_for(waiter, timeout)

    def _claim_terminal(self, event: ResponseStateEvent) -> bool:
        if self._terminal is not None:
            return False
        self._terminal = event
        return True

    def _resolve_terminal(self, event: ResponseStateEvent) -> None:
        if not self._terminal_future.done():
            self._terminal_future.set_result(event)


class PromptStream(ResponseHandle):
    def __init__(self, request_id: str, response_id: str, send_event: SendEvent) -> None:
        super().__init__(request_id, response_id)
        self._send_event = send_event
        self._lock = asyncio.Lock()
        self._next_seq = 1
        self._done = False

    async def send(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("prompt chunk text must be a string")
        async with self._lock:
            if self._done:
                raise PromptStreamClosedError("prompt stream is already done")
            seq = self._next_seq
            await self._send_event(
                DataChannelEvent(
                    event="system.prompt.chunk",
                    data={"text": text},
                    request_id=self.request_id,
                    response_id=self.response_id,
                    seq=seq,
                    timestamp=time.time_ns() // 1_000_000,
                )
            )
            self._next_seq += 1

    async def done(self) -> None:
        async with self._lock:
            if self._done:
                return
            await self._send_event(
                DataChannelEvent(
                    event="system.prompt.done",
                    request_id=self.request_id,
                    response_id=self.response_id,
                )
            )
            self._done = True


class AudioResponse(ResponseHandle):
    def __init__(
        self,
        request_id: str,
        response_id: str,
        send_event: SendEvent,
        send_audio: SendAudio,
        send_audio_stream: SendAudioStream,
    ) -> None:
        super().__init__(request_id, response_id)
        self._send_event = send_event
        self._send_audio = send_audio
        self._send_audio_stream = send_audio_stream
        self._done = False
        self._lock = asyncio.Lock()

    async def send(self, frame: AudioFrame) -> None:
        if self._done:
            raise PromptStreamClosedError("audio response is already done")
        await self._send_audio(frame)

    async def send_stream(self, frames: AsyncIterable[AudioFrame]) -> None:
        if self._done:
            raise PromptStreamClosedError("audio response is already done")
        await self._send_audio_stream(frames)

    async def done(self) -> None:
        async with self._lock:
            if self._done:
                return
            await self._send_event(
                DataChannelEvent(
                    event="response.audio.finish",
                    request_id=self.request_id,
                    response_id=self.response_id,
                )
            )
            self._done = True
