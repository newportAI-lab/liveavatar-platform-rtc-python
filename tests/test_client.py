import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from liveavatar_rtc.client import PlatformRTCClient
from liveavatar_rtc.errors import APIError, RTCConnectionError, SessionStartError
from liveavatar_rtc.types import FrontendConnection, SessionInfo


@pytest.fixture
def info():
    return SessionInfo("sess-abc", "agent-token", "user-token", "wss://sfu")


@pytest.fixture
def api(info):
    value = MagicMock()
    value.start_session = AsyncMock(return_value=info)
    value.stop_session = AsyncMock()
    value.aclose = AsyncMock()
    return value


@pytest.fixture
def manager():
    value = MagicMock()
    value.connect = AsyncMock()
    value.disconnect = AsyncMock()
    value.wait_for_user = AsyncMock(side_effect=AssertionError("must not wait"))
    value.session_id = "sess-abc"
    value.sfu_url = "wss://sfu"
    value.user_token = "user-token"
    value.events = MagicMock()
    return value


@pytest.fixture
def manager_factory(manager):
    with patch("liveavatar_rtc.client.LiveKitManager", return_value=manager) as factory:
        yield factory


@pytest.fixture
def client(api):
    value = PlatformRTCClient(api_key="key", avatar_id="avatar")
    value._api = api
    return value


def test_client_has_split_sample_rates():
    signature = inspect.signature(PlatformRTCClient)
    assert signature.parameters["input_sample_rate"].default == 16000
    assert signature.parameters["output_sample_rate"].default == 24000
    assert "sample_rate" not in signature.parameters
    assert not hasattr(PlatformRTCClient, "connect_async")


@pytest.mark.asyncio
async def test_connect_returns_after_agent_track_publish(client, api, manager, manager_factory):
    session = await asyncio.wait_for(client.connect(), timeout=0.1)
    assert session.is_agent_connected
    manager.connect.assert_awaited_once()
    manager.wait_for_user.assert_not_called()
    api.start_session.assert_awaited_once_with("avatar")
    manager_factory.assert_called_once_with(
        session_id="sess-abc",
        sfu_url="wss://sfu",
        agent_token="agent-token",
        user_token="user-token",
        input_sample_rate=16000,
        output_sample_rate=24000,
    )


@pytest.mark.asyncio
async def test_server_output_rate_overrides_default(client, api, manager_factory):
    api.start_session.return_value = SessionInfo(
        "sess-abc", "agent-token", "user-token", "wss://sfu", 48000
    )
    await client.connect()
    assert manager_factory.call_args.kwargs["output_sample_rate"] == 48000


@pytest.mark.asyncio
async def test_session_exposes_frontend_safe_connection(client, manager_factory):
    session = await client.connect()
    assert session.connection == FrontendConnection("user-token", "wss://sfu")
    assert not hasattr(session.connection, "agent_token")


@pytest.mark.asyncio
async def test_connect_reuses_only_open_session(client, api, manager_factory):
    first = await client.connect()
    assert await client.connect() is first
    api.start_session.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [APIError(1, "no"), SessionStartError("bad")])
async def test_start_failure_preserves_error_and_closes_http(client, api, error):
    api.start_session.side_effect = error
    with pytest.raises(type(error)) as raised:
        await client.connect()
    assert raised.value is error
    api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_rtc_failure_is_wrapped_and_all_cleanup_runs(
    client, api, manager, manager_factory
):
    primary = RuntimeError("publish failed")
    manager.connect.side_effect = primary
    manager.disconnect.side_effect = RuntimeError("disconnect failed")
    api.stop_session.side_effect = RuntimeError("stop failed")
    api.aclose.side_effect = RuntimeError("close failed")

    with pytest.raises(RTCConnectionError) as raised:
        await client.connect()

    assert raised.value.__cause__ is primary
    manager.disconnect.assert_awaited_once()
    api.stop_session.assert_awaited_once_with("sess-abc")
    api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_construction_failure_preserves_error_and_cleans_up(client, api):
    primary = RuntimeError("manager construction failed")
    with patch("liveavatar_rtc.client.LiveKitManager", side_effect=primary):
        with pytest.raises(RuntimeError) as raised:
            await client.connect()
    assert raised.value is primary
    api.stop_session.assert_awaited_once_with("sess-abc")
    api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_construction_failure_preserves_error_and_cleans_up(
    client, api, manager, manager_factory
):
    primary = ValueError("bad session")
    with patch("liveavatar_rtc.client.Session", side_effect=primary):
        with pytest.raises(ValueError) as raised:
            await client.connect()
    assert raised.value is primary
    manager.disconnect.assert_awaited_once()
    api.stop_session.assert_awaited_once_with("sess-abc")
    api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_preserves_close_error_and_finishes_cleanup(
    client, api, manager, manager_factory
):
    session = await client.connect()
    primary = RuntimeError("rtc close failed")
    session.close = AsyncMock(side_effect=primary)
    api.stop_session.side_effect = RuntimeError("stop failed")
    api.aclose.side_effect = RuntimeError("http close failed")

    with pytest.raises(RuntimeError) as raised:
        await client.disconnect()
    assert raised.value is primary
    api.stop_session.assert_awaited_once_with("sess-abc")
    api.aclose.assert_awaited_once()
    assert client._session is None


@pytest.mark.asyncio
async def test_disconnect_is_idempotent(client, api, manager, manager_factory):
    await client.connect()
    await asyncio.gather(client.disconnect(), client.disconnect())
    manager.disconnect.assert_awaited_once()
    api.stop_session.assert_awaited_once_with("sess-abc")
    api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager_preserves_body_error(client, api, manager_factory):
    with pytest.raises(ValueError, match="body"):
        async with client:
            api.stop_session.side_effect = RuntimeError("cleanup")
            raise ValueError("body")
    api.aclose.assert_awaited_once()


def cycle_api(session_id):
    value = MagicMock()
    value.start_session = AsyncMock(
        return_value=SessionInfo(
            session_id, f"agent-{session_id}", f"user-{session_id}", "wss://sfu"
        )
    )
    value.stop_session = AsyncMock()
    value.aclose = AsyncMock()
    return value


def cycle_manager(session_id):
    value = MagicMock()
    value.connect = AsyncMock()
    value.disconnect = AsyncMock()
    value.session_id = session_id
    value.sfu_url = "wss://sfu"
    value.user_token = f"user-{session_id}"
    value.events = MagicMock()
    return value


@pytest.mark.asyncio
async def test_reconnect_after_disconnect_uses_a_new_api_cycle():
    first_api, second_api = cycle_api("one"), cycle_api("two")
    first_manager, second_manager = cycle_manager("one"), cycle_manager("two")
    with (
        patch("liveavatar_rtc.client.ApiClient", side_effect=[first_api, second_api]),
        patch(
            "liveavatar_rtc.client.LiveKitManager",
            side_effect=[first_manager, second_manager],
        ),
    ):
        client = PlatformRTCClient("key", "avatar")
        await client.connect()
        await client.disconnect()
        session = await client.connect()
    assert session.session_id == "two"
    second_api.start_session.assert_awaited_once_with("avatar")


@pytest.mark.asyncio
async def test_retry_after_connect_failure_uses_a_new_api_cycle():
    first_api, second_api = cycle_api("one"), cycle_api("two")
    bad_manager, good_manager = cycle_manager("one"), cycle_manager("two")
    bad_manager.connect.side_effect = RuntimeError("connect failed")
    with (
        patch("liveavatar_rtc.client.ApiClient", side_effect=[first_api, second_api]),
        patch(
            "liveavatar_rtc.client.LiveKitManager",
            side_effect=[bad_manager, good_manager],
        ),
    ):
        client = PlatformRTCClient("key", "avatar")
        with pytest.raises(RTCConnectionError):
            await client.connect()
        session = await client.connect()
    assert session.session_id == "two"
    second_api.start_session.assert_awaited_once_with("avatar")


@pytest.mark.asyncio
async def test_reconnect_after_direct_session_close_finalizes_old_cycle():
    first_api, second_api = cycle_api("one"), cycle_api("two")
    first_manager, second_manager = cycle_manager("one"), cycle_manager("two")
    with (
        patch("liveavatar_rtc.client.ApiClient", side_effect=[first_api, second_api]),
        patch(
            "liveavatar_rtc.client.LiveKitManager",
            side_effect=[first_manager, second_manager],
        ),
    ):
        client = PlatformRTCClient("key", "avatar")
        old_session = await client.connect()
        await old_session.close()
        new_session = await client.connect()
    assert new_session.session_id == "two"
    first_api.stop_session.assert_awaited_once_with("one")
    first_api.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_cycle_disconnect_cleans_the_new_session():
    first_api, second_api = cycle_api("one"), cycle_api("two")
    first_manager, second_manager = cycle_manager("one"), cycle_manager("two")
    with (
        patch("liveavatar_rtc.client.ApiClient", side_effect=[first_api, second_api]),
        patch(
            "liveavatar_rtc.client.LiveKitManager",
            side_effect=[first_manager, second_manager],
        ),
    ):
        client = PlatformRTCClient("key", "avatar")
        await client.connect()
        await client.disconnect()
        await client.connect()
        await client.disconnect()
    second_manager.disconnect.assert_awaited_once()
    second_api.stop_session.assert_awaited_once_with("two")
    second_api.aclose.assert_awaited_once()
