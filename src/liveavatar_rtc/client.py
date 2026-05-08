from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from .api_client import ApiClient, ApiError
from .event_dispatcher import EventDispatcher
from .livekit_manager import LiveKitManager
from .session import Session

logger = logging.getLogger(__name__)

Callback = Callable[..., Any]

_DEFAULT_BASE_URL = "https://facemarket.ai/vih/dispatcher"


class PlatformRTCClient:
    """Main entry point for Live Avatar Platform RTC mode.

    Usage::

        client = PlatformRTCClient(api_key="lf_...", avatar_id="avatar-xxx")
        async with client as session:
            @session.on("user_audio_frame")
            async def on_audio(frame):
                ...  # ASR → LLM → TTS → session.publish_audio(...)
    """

    def __init__(
        self,
        api_key: str,
        avatar_id: str,
        base_url: str | None = None,
        sample_rate: int = 16000,
        sandbox: bool = False,
    ) -> None:
        if base_url is None:
            base_url = os.environ.get("LIVEAVATAR_BASE_URL", _DEFAULT_BASE_URL)
        self._api = ApiClient(api_key=api_key, base_url=base_url, sandbox=sandbox)
        self._avatar_id = avatar_id
        self._sample_rate = sample_rate
        self._sandbox = sandbox
        self._session: Session | None = None
        self._events = EventDispatcher()

    # ── Connection Lifecycle Callbacks ──────────────────────

    def on(self, event: str) -> Callable[[Callback], Callback]:
        """Decorator for client-level events: "connection_established", "connection_closed"."""
        return self._events.on(event)

    # ── Connect ─────────────────────────────────────────────

    async def connect(self) -> Session:
        """Start a session: call /session/start, join LiveKit room as agent_{sessionId}."""
        if self._session is not None:
            return self._session

        info = await self._api.start_session(self._avatar_id)
        logger.info(
            "Session started: sessionId=%s", info.session_id
        )

        lk = LiveKitManager(
            session_id=info.session_id,
            sfu_url=info.sfu_url,
            agent_token=info.agent_token,
            user_token=info.user_token,
            sample_rate=self._sample_rate,
        )

        try:
            await lk.connect()
            await lk.wait_until_ready()
        except Exception:
            await lk.disconnect()
            try:
                await self._api.stop_session(info.session_id)
            except Exception:
                logger.debug(
                    "stop_session failed for %s during failed connect cleanup",
                    info.session_id,
                    exc_info=True,
                )
            raise

        self._session = Session(lk)
        await self._events.dispatch("connection_established", self._session)
        return self._session

    async def connect_async(self) -> Session:
        """Alias for connect()."""
        return await self.connect()

    # ── Disconnect ──────────────────────────────────────────

    async def disconnect(self) -> None:
        if self._session is not None:
            session_id = self._session.session_id
            await self._session.close()
            try:
                await self._api.stop_session(session_id)
            except Exception:
                logger.debug("stop_session failed for %s", session_id, exc_info=True)
            await self._events.dispatch("connection_closed", session_id)
            self._session = None
        await self._api.aclose()

    async def __aenter__(self) -> Session:
        return await self.connect()

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
