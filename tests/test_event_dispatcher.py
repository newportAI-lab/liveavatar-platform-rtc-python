import asyncio

import pytest

from liveavatar_rtc.event_dispatcher import EventDispatcher


class TestEventDispatcher:
    def test_add_and_dispatch_single_handler(self):
        dispatcher = EventDispatcher()
        received = []

        async def handler(arg1, arg2):
            received.append((arg1, arg2))

        dispatcher.add("test.event", handler)
        asyncio.run(dispatcher.dispatch("test.event", "hello", 42))

        assert received == [("hello", 42)]

    def test_add_and_dispatch_multiple_handlers(self):
        dispatcher = EventDispatcher()
        received = []

        async def handler1(data):
            received.append(("h1", data))

        async def handler2(data):
            received.append(("h2", data))

        dispatcher.add("evt", handler1)
        dispatcher.add("evt", handler2)
        asyncio.run(dispatcher.dispatch("evt", "x"))

        assert received == [("h1", "x"), ("h2", "x")]

    def test_on_decorator_registers_handler(self):
        dispatcher = EventDispatcher()
        received = []

        @dispatcher.on("my.event")
        async def my_handler(value):
            received.append(value)

        asyncio.run(dispatcher.dispatch("my.event", 99))
        assert received == [99]

    def test_on_decorator_returns_callback(self):
        dispatcher = EventDispatcher()

        @dispatcher.on("evt")
        async def handler():
            pass

        assert handler is not None

    def test_dispatch_no_handlers_is_noop(self):
        dispatcher = EventDispatcher()
        asyncio.run(dispatcher.dispatch("no.handlers", "data"))
        # Should not raise

    def test_dispatch_different_events_dont_interfere(self):
        dispatcher = EventDispatcher()
        received_a = []
        received_b = []

        async def handler_a(x):
            received_a.append(x)

        async def handler_b(x):
            received_b.append(x)

        dispatcher.add("event.a", handler_a)
        dispatcher.add("event.b", handler_b)

        asyncio.run(dispatcher.dispatch("event.a", 1))
        asyncio.run(dispatcher.dispatch("event.b", 2))

        assert received_a == [1]
        assert received_b == [2]

    def test_wildcard_matches_all_events(self):
        dispatcher = EventDispatcher()
        wildcard_events = []

        async def catch_all(event_name, *args, **kwargs):
            wildcard_events.append((event_name, args, kwargs))

        dispatcher.add("*", catch_all)
        asyncio.run(dispatcher.dispatch("foo", 1))
        asyncio.run(dispatcher.dispatch("bar", 2, key="val"))

        assert len(wildcard_events) == 2
        assert wildcard_events[0] == ("foo", (1,), {})
        assert wildcard_events[1] == ("bar", (2,), {"key": "val"})

    def test_wildcard_fires_alongside_specific_handler(self):
        dispatcher = EventDispatcher()
        specific_calls = []
        wildcard_calls = []

        async def specific(data):
            specific_calls.append(data)

        async def wildcard(event, data):
            wildcard_calls.append((event, data))

        dispatcher.add("x", specific)
        dispatcher.add("*", wildcard)
        asyncio.run(dispatcher.dispatch("x", "payload"))

        assert specific_calls == ["payload"]
        assert wildcard_calls == [("x", "payload")]

    def test_remove_handler(self):
        dispatcher = EventDispatcher()
        received = []

        async def handler(data):
            received.append(data)

        dispatcher.add("evt", handler)
        asyncio.run(dispatcher.dispatch("evt", 1))
        assert received == [1]

        dispatcher.remove("evt", handler)
        asyncio.run(dispatcher.dispatch("evt", 2))
        assert received == [1]  # no new call

    def test_remove_nonexistent_handler_no_error(self):
        dispatcher = EventDispatcher()

        async def handler():
            pass

        dispatcher.remove("evt", handler)  # Should not raise

    def test_remove_from_event_with_no_handlers(self):
        dispatcher = EventDispatcher()

        async def handler():
            pass

        dispatcher.remove("nonexistent", handler)  # Should not raise

    def test_handler_order_is_preserved(self):
        dispatcher = EventDispatcher()
        order = []

        async def first():
            order.append(1)

        async def second():
            order.append(2)

        async def third():
            order.append(3)

        dispatcher.add("evt", first)
        dispatcher.add("evt", second)
        dispatcher.add("evt", third)
        asyncio.run(dispatcher.dispatch("evt"))

        assert order == [1, 2, 3]

    def test_dispatch_with_kwargs(self):
        dispatcher = EventDispatcher()
        received = {}

        async def handler(**kwargs):
            received.update(kwargs)

        dispatcher.add("evt", handler)
        asyncio.run(dispatcher.dispatch("evt", a=1, b=2))

        assert received == {"a": 1, "b": 2}

    def test_handler_exception_does_not_cascade(self, caplog):
        """A handler that raises must not prevent subsequent handlers from running."""
        dispatcher = EventDispatcher()
        second_called = False

        async def bad_handler():
            raise RuntimeError("handler failure")

        async def good_handler():
            nonlocal second_called
            second_called = True

        dispatcher.add("evt", bad_handler)
        dispatcher.add("evt", good_handler)
        asyncio.run(dispatcher.dispatch("evt"))

        assert second_called
        assert "Handler failed for event 'evt'" in caplog.text

    def test_multiple_registrations_same_handler(self):
        dispatcher = EventDispatcher()
        count = 0

        async def handler():
            nonlocal count
            count += 1

        dispatcher.add("evt", handler)
        dispatcher.add("evt", handler)
        asyncio.run(dispatcher.dispatch("evt"))

        assert count == 2  # Called twice, once per add
