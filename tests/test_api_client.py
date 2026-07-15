import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from liveavatar_rtc import APIError, SessionInfo, SessionStartError
from liveavatar_rtc.api_client import ApiClient


@pytest.fixture
def client():
    """Create an ApiClient with _client mocked."""
    api = ApiClient(api_key="lf_test_key", base_url="https://test.example.com/api")
    mock_http = AsyncMock()
    api._client = mock_http
    return api, mock_http


class TestSessionInfo:
    def test_basic_fields(self):
        info = SessionInfo(
            session_id="sess-123",
            agent_token="tok-abc",
            user_token="user-tok-xyz",
            sfu_url="wss://sfu.example.com",
        )
        assert info.session_id == "sess-123"
        assert info.agent_token == "tok-abc"
        assert info.user_token == "user-tok-xyz"
        assert info.sfu_url == "wss://sfu.example.com"


class TestApiClientStartSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "code": 0,
            "data": {
                "sessionId": "sess-abc", "roomId": "room-xyz",
                "agentToken": "agent-tok", "sfuUrl": "wss://sfu.example.com",
            },
        })
        mock_http.post.return_value = mock_resp

        info = await api.start_session("avatar-1")

        assert mock_http.post.call_args.kwargs["json"] == {
            "avatarId": "avatar-1",
            "mode": "rtcAgent",
        }
        assert info.session_id == "sess-abc"
        assert info.agent_token == "agent-tok"
        assert info.sfu_url == "wss://sfu.example.com"
        assert info.output_sample_rate is None

    @pytest.mark.asyncio
    async def test_output_sample_rate(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "code": 0,
            "data": {
                "sessionId": "sess-custom",
                "agentToken": "tok",
                "userToken": "user-tok",
                "sfuUrl": "wss://sfu.example.com",
                "outputSampleRate": 24000,
            },
        })
        mock_http.post.return_value = mock_resp

        info = await api.start_session("avatar-1")

        assert info.output_sample_rate == 24000

    def test_has_only_avatar_id_parameter(self):
        parameters = inspect.signature(ApiClient.start_session).parameters
        assert list(parameters) == ["self", "avatar_id"]

    @pytest.mark.asyncio
    async def test_api_error_nonzero_code(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"code": 1001, "message": "Avatar not found"})
        mock_http.post.return_value = mock_resp

        with pytest.raises(APIError) as exc_info:
            await api.start_session("bad-avatar")
        assert exc_info.value.code == 1001
        assert "Avatar not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_api_error_no_message(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"code": 5000})
        mock_http.post.return_value = mock_resp

        with pytest.raises(APIError) as exc_info:
            await api.start_session("avatar-1")
        assert exc_info.value.code == 5000
        assert "unknown error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_api_error_missing_data_field(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"code": 0})
        mock_http.post.return_value = mock_resp

        with pytest.raises(SessionStartError) as exc_info:
            await api.start_session("avatar-1")
        assert "missing sessionId, sfuUrl, or agentToken" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_api_error_missing_required_fields(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"code": 0, "data": {"sessionId": ""}})
        mock_http.post.return_value = mock_resp

        with pytest.raises(SessionStartError) as exc_info:
            await api.start_session("avatar-1")
        assert "missing sessionId, sfuUrl, or agentToken" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_error(self, client):
        api, mock_http = client
        mock_http.post.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with pytest.raises(httpx.HTTPStatusError):
            await api.start_session("avatar-1")

    @pytest.mark.asyncio
    async def test_network_error(self, client):
        api, mock_http = client
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            await api.start_session("avatar-1")

    @pytest.mark.asyncio
    async def test_timeout_error(self, client):
        api, mock_http = client
        mock_http.post.side_effect = httpx.ReadTimeout("timeout")

        with pytest.raises(httpx.ReadTimeout):
            await api.start_session("avatar-1")

    @pytest.mark.asyncio
    async def test_sandbox_header(self):
        api = ApiClient(api_key="lf_key", base_url="https://test.example.com", sandbox=True)
        mock_http = AsyncMock()
        api._client = mock_http
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "code": 0,
            "data": {"sessionId": "sess-1", "agentToken": "tok", "sfuUrl": "wss://sfu.example.com"},
        })
        mock_http.post.return_value = mock_resp

        await api.start_session("avatar-1")

        headers = mock_http.post.call_args.kwargs["headers"]
        assert headers["X-Env-Sandbox"] == "true"

    @pytest.mark.asyncio
    async def test_normal_mode_no_sandbox_header(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "code": 0,
            "data": {"sessionId": "sess-1", "agentToken": "tok", "sfuUrl": "wss://sfu.example.com"},
        })
        mock_http.post.return_value = mock_resp

        await api.start_session("avatar-1")

        headers = mock_http.post.call_args.kwargs["headers"]
        assert "X-Env-Sandbox" not in headers

    @pytest.mark.asyncio
    async def test_agent_token_is_required(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "code": 0,
            "data": {"sessionId": "sess-min", "sfuUrl": "wss://sfu.example.com"},
        })
        mock_http.post.return_value = mock_resp

        with pytest.raises(SessionStartError):
            await api.start_session("avatar-1")


class TestApiClientStopSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        api, mock_http = client
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"code": 0})
        mock_http.post.return_value = mock_resp

        await api.stop_session("sess-123")

        assert mock_http.post.call_args.kwargs["json"] == {"sessionId": "sess-123"}

    @pytest.mark.asyncio
    async def test_http_error(self, client):
        api, mock_http = client
        mock_http.post.side_effect = httpx.HTTPStatusError(
            "Not found", request=MagicMock(), response=MagicMock(status_code=404)
        )

        with pytest.raises(httpx.HTTPStatusError):
            await api.stop_session("bad-sess")


class TestApiClientHeaders:
    def test_bearer_token(self, client):
        api, _ = client
        headers = api._headers()
        assert headers["Authorization"] == "Bearer lf_test_key"
        assert headers["Content-Type"] == "application/json"

    def test_sandbox_header_in_headers_method(self):
        api = ApiClient(api_key="lf_key", base_url="https://test.example.com", sandbox=True)
        headers = api._headers()
        assert headers["X-Env-Sandbox"] == "true"


class TestApiError:
    def test_str_representation(self):
        error = APIError(1001, "Avatar not found")
        assert "1001" in str(error)
        assert "Avatar not found" in str(error)
        assert error.code == 1001
        assert error.message == "Avatar not found"
