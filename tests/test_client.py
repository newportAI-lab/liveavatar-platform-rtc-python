import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from liveavatar_rtc.api_client import ApiError, SessionInfo
from liveavatar_rtc.client import PlatformRTCClient


@pytest.fixture
def session_info():
    return SessionInfo(
        session_id="sess-abc",
        agent_token="agent-tok-123",
        user_token="user-tok-456",
        sfu_url="wss://sfu.test.com",
    )


@pytest.fixture
def mock_api(session_info):
    api = MagicMock()
    api.start_session = AsyncMock(return_value=session_info)
    api.stop_session = AsyncMock()
    api.aclose = AsyncMock()
    return api


@pytest.fixture
def mock_lk_manager():
    with patch("liveavatar_rtc.client.LiveKitManager") as mock_cls:
        lk = MagicMock()
        lk.connect = AsyncMock()
        lk.wait_until_ready = AsyncMock()
        lk.disconnect = AsyncMock()
        lk.session_id = "sess-abc"
        lk.sfu_url = "wss://sfu.test.com"
        lk.user_token = "user-tok-456"
        mock_cls.return_value = lk
        yield mock_cls, lk


class TestPlatformRTCClientInit:
    def test_default_values(self):
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-1")
        assert client._api._api_key == "key"
        assert client._avatar_id == "avatar-1"
        assert client._sample_rate == 16000
        assert client._sandbox is False
        assert client._session is None

    def test_custom_values(self):
        client = PlatformRTCClient(
            api_key="key", avatar_id="avatar-2",
            base_url="https://custom.example.com", sample_rate=24000, sandbox=True,
        )
        assert client._avatar_id == "avatar-2"
        assert client._sample_rate == 24000
        assert client._sandbox is True

    def test_client_level_events(self):
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-1")
        @client.on("connection_established")
        async def h1(session): pass
        @client.on("connection_closed")
        async def h2(session_id): pass
        assert len(client._events._handlers.get("connection_established", [])) == 1
        assert len(client._events._handlers.get("connection_closed", [])) == 1


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self, mock_api, mock_lk_manager, session_info):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        session = await client.connect()

        mock_api.start_session.assert_called_once_with("avatar-123")
        mock_lk_cls.assert_called_once_with(
            session_id="sess-abc", sfu_url="wss://sfu.test.com",
            agent_token="agent-tok-123", user_token="user-tok-456",
            sample_rate=16000,
        )
        mock_lk.connect.assert_called_once()
        mock_lk.wait_until_ready.assert_called_once()
        assert session is not None
        assert session.session_id == "sess-abc"
        assert client._session is session

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        session1 = await client.connect()
        session2 = await client.connect()

        assert session1 is session2
        mock_api.start_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_api_error(self, mock_api):
        mock_api.start_session.side_effect = ApiError(1001, "Avatar not found")
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        with pytest.raises(ApiError, match="Avatar not found"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_connect_livekit_error_disconnects(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        mock_lk.connect.side_effect = RuntimeError("Connection refused")
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        with pytest.raises(RuntimeError, match="Connection refused"):
            await client.connect()

        mock_lk.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_livekit_ready_timeout(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        mock_lk.wait_until_ready.side_effect = asyncio.TimeoutError()
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        with pytest.raises(asyncio.TimeoutError):
            await client.connect()

        mock_lk.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_dispatches_established_event(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api
        received = []

        @client.on("connection_established")
        async def handler(session):
            received.append(session)

        session = await client.connect()
        assert len(received) == 1
        assert received[0] is session

    @pytest.mark.asyncio
    async def test_connect_async_alias(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        session = await client.connect_async()
        assert session is not None
        assert session.session_id == "sess-abc"


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        await client.connect()
        await client.disconnect()

        mock_lk.disconnect.assert_called_once()
        mock_api.stop_session.assert_called_once_with("sess-abc")
        assert client._session is None

    @pytest.mark.asyncio
    async def test_disconnect_no_session_noop(self):
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        await client.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_disconnect_dispatches_closed_event(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api
        received = []

        @client.on("connection_closed")
        async def handler(session_id):
            received.append(session_id)

        await client.connect()
        await client.disconnect()

        assert received == ["sess-abc"]


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        async with client as session:
            assert session is not None
            assert session.session_id == "sess-abc"
            assert client._session is session

        mock_lk.disconnect.assert_called_once()
        mock_api.stop_session.assert_called_once_with("sess-abc")
        assert client._session is None

    @pytest.mark.asyncio
    async def test_async_context_manager_exception_cleanup(self, mock_api, mock_lk_manager):
        mock_lk_cls, mock_lk = mock_lk_manager
        client = PlatformRTCClient(api_key="key", avatar_id="avatar-123")
        client._api = mock_api

        with pytest.raises(ValueError, match="test error"):
            async with client as session:
                raise ValueError("test error")

        mock_lk.disconnect.assert_called_once()
        assert client._session is None
