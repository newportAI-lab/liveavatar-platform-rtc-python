import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Callback = Callable[..., Any]


class EventDispatcher:
    """String event name → callback dispatch with wildcard support."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callback]] = {}

    def on(self, event: str) -> Callable[[Callback], Callback]:
        """Decorator: register a callback for an event name."""

        def decorator(callback: Callback) -> Callback:
            self.add(event, callback)
            return callback

        return decorator

    def add(self, event: str, callback: Callback) -> None:
        self._handlers.setdefault(event, []).append(callback)

    def remove(self, event: str, callback: Callback) -> None:
        handlers = self._handlers.get(event, [])
        if callback in handlers:
            handlers.remove(callback)
        if not handlers:
            self._handlers.pop(event, None)

    async def dispatch(self, event: str, *args: Any, **kwargs: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Handler failed for event '%s'", event)
        for handler in list(self._handlers.get("*", [])):
            try:
                result = handler(event, *args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Wildcard handler failed for event '%s'", event)
