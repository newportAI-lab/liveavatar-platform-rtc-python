from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from .api_client import ApiClient
from .errors import RTCConnectionError
from .event_dispatcher import EventDispatcher
from .livekit_manager import LiveKitManager
from .session import Session

logger = logging.getLogger(__name__)

Callback = Callable[..., Any]
_DEFAULT_BASE_URL = "https://facemarket.ai/vih/dispatcher"


class PlatformRTCClient:
    """Main entry point for Live Avatar Platform RTC agent sessions."""

    def __init__(
        self,
        api_key: str,
        avatar_id: str,
        base_url: str | None = None,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        sandbox: bool = False,
    ) -> None:
        if base_url is None:
            base_url = os.environ.get("LIVEAVATAR_BASE_URL", _DEFAULT_BASE_URL)
        self._api_key = api_key
        self._base_url = base_url
        self._sandbox = sandbox
        self._api = self._new_api()
        self._avatar_id = avatar_id
        self._input_sample_rate = input_sample_rate
        self._output_sample_rate = output_sample_rate
        self._session: Session | None = None
        self._events = EventDispatcher()
        self._disconnect_task: asyncio.Task[None] | None = None
        self._api_closed = False

    def on(self, event: str) -> Callable[[Callback], Callback]:
        return self._events.on(event)

    def _new_api(self) -> ApiClient:
        return ApiClient(
            api_key=self._api_key,
            base_url=self._base_url,
            sandbox=self._sandbox,
        )

    async def _prepare_connect_cycle(self) -> None:
        try:
            if self._session is not None and self._session.is_closed:
                await self.disconnect()
            elif self._disconnect_task is not None:
                await asyncio.shield(self._disconnect_task)
        except Exception:
            logger.debug(
                "previous connection cycle cleanup failed before reconnect",
                exc_info=True,
            )

        if self._api_closed:
            self._api = self._new_api()
            self._api_closed = False
            self._disconnect_task = None

    async def _close_api(self) -> None:
        if self._api_closed:
            return
        self._api_closed = True
        await self._api.aclose()

    @staticmethod
    async def _try_cleanup(operation: Callable[[], Awaitable[None]], label: str) -> None:
        try:
            await operation()
        except BaseException:
            logger.debug("%s failed during cleanup", label, exc_info=True)

    async def _cleanup_failed_connect(
        self, session_id: str, manager: LiveKitManager
    ) -> None:
        await self._try_cleanup(manager.disconnect, "RTC disconnect")
        await self._cleanup_started_session(session_id)

    async def _cleanup_started_session(self, session_id: str) -> None:
        await self._try_cleanup(
            lambda: self._api.stop_session(session_id), "remote session stop"
        )
        await self._try_cleanup(self._close_api, "HTTP client close")

    async def connect(self) -> Session:
        if self._session is not None and not self._session.is_closed:
            return self._session
        await self._prepare_connect_cycle()

        try:
            info = await self._api.start_session(self._avatar_id)
        except BaseException:
            await self._try_cleanup(self._close_api, "HTTP client close")
            raise

        output_rate = info.output_sample_rate or self._output_sample_rate
        try:
            manager = LiveKitManager(
                session_id=info.session_id,
                sfu_url=info.sfu_url,
                agent_token=info.agent_token,
                user_token=info.user_token,
                input_sample_rate=self._input_sample_rate,
                output_sample_rate=output_rate,
            )
        except BaseException:
            await self._cleanup_started_session(info.session_id)
            raise

        try:
            await manager.connect()
        except Exception as exc:
            await self._cleanup_failed_connect(info.session_id, manager)
            raise RTCConnectionError(
                f"failed to connect RTC session {info.session_id}"
            ) from exc
        except BaseException:
            await self._cleanup_failed_connect(info.session_id, manager)
            raise

        try:
            session = Session(manager)
            self._session = session
            await self._events.dispatch("connection_established", session)
        except BaseException:
            self._session = None
            await self._cleanup_failed_connect(info.session_id, manager)
            raise
        return session

    async def disconnect(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._disconnect())
        await asyncio.shield(self._disconnect_task)

    async def _disconnect(self) -> None:
        session = self._session
        self._session = None
        primary: BaseException | None = None

        async def run(operation: Callable[[], Awaitable[None]], label: str) -> None:
            nonlocal primary
            try:
                await operation()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    logger.debug("%s failed after an earlier cleanup error", label, exc_info=True)

        if session is not None:
            await run(session.close, "RTC disconnect")
            await run(
                lambda: self._api.stop_session(session.session_id),
                "remote session stop",
            )
            await run(
                lambda: self._events.dispatch("connection_closed", session.session_id),
                "connection_closed dispatch",
            )
        await run(self._close_api, "HTTP client close")
        if primary is not None:
            raise primary

    async def __aenter__(self) -> Session:
        return await self.connect()

    async def __aexit__(self, *args: Any) -> None:
        try:
            await self.disconnect()
        except BaseException:
            if len(args) > 1 and args[1] is not None:
                logger.debug("cleanup failed while leaving context", exc_info=True)
                return
            raise
