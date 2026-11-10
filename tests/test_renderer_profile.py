"""Model request and Client-to-ApiClient contract, without connecting to RTC."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from liveavatar_rtc.api_client import ApiClient
from liveavatar_rtc.client import PlatformRTCClient

@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, "normal", "pet", "4k"])
async def test_model_body(profile):
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {
            "sessionId": "test", "sfuUrl": "wss://invalid", "agentToken": "test"}})
    api = ApiClient("test", "https://invalid")
    await api.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        api._client = client
        await api.start_session("avatar", renderer_profile=profile)
    assert ("rendererProfile" in captured[0]) == (profile is not None)
    if profile is not None:
        assert captured[0]["rendererProfile"] == profile

@pytest.mark.asyncio
async def test_client_forwards_model_before_connecting_rtc():
    client = PlatformRTCClient("test", "avatar", renderer_profile="pet")
    client._api.start_session = AsyncMock(side_effect=RuntimeError("capture boundary"))
    with pytest.raises(RuntimeError, match="capture boundary"):
        await client.connect()
    client._api.start_session.assert_awaited_once_with("avatar", None, renderer_profile="pet")

@pytest.mark.parametrize("profile", ["", "PET", "pet ", "baby", 1, True, {}, []])
def test_invalid_model_rejected_before_http_client_creation(profile):
    with pytest.raises(ValueError):
        PlatformRTCClient("test", "avatar", renderer_profile=profile)
