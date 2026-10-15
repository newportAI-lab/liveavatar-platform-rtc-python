import httpx

from .errors import APIError, SessionStartError
from .types import SessionInfo


class ApiClient:
    """REST client for Live Avatar platform session management."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://facemarket.ai/vih/dispatcher",
        sandbox: bool = False,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._sandbox = sandbox
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._sandbox:
            h["X-Env-Sandbox"] = "true"
        return h

    async def start_session(
        self,
        avatar_id: str,
        external_audio_config: dict | None = None,
    ) -> SessionInfo:
        body: dict = {"avatarId": avatar_id, "mode": "rtcAgent"}
        if external_audio_config is not None:
            body["externalAudioConfig"] = external_audio_config
        resp = await self._client.post(
            f"{self._base_url}/v1/session/start",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        payload: dict = resp.json()

        if payload.get("code") != 0:
            raise APIError(
                payload.get("code"), payload.get("message", "unknown error")
            )

        data = payload.get("data") or {}
        session_id = data.get("sessionId", "")
        sfu_url = data.get("sfuUrl", "")
        agent_token = data.get("agentToken", "")
        if not session_id or not sfu_url or not agent_token:
            raise SessionStartError(
                "session response is missing sessionId, sfuUrl, or agentToken"
            )

        return SessionInfo(
            session_id=session_id,
            agent_token=agent_token,
            user_token=data.get("userToken", ""),
            sfu_url=sfu_url,
            output_sample_rate=data.get("outputSampleRate"),
        )

    async def stop_session(self, session_id: str) -> None:
        resp = await self._client.post(
            f"{self._base_url}/v1/session/stop",
            headers=self._headers(),
            json={"sessionId": session_id},
        )
        resp.raise_for_status()
        data: dict = resp.json()
        if data.get("code") != 0:
            raise APIError(
                data.get("code", -1), data.get("message", "unknown error")
            )
