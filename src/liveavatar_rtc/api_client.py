from dataclasses import dataclass

import httpx


@dataclass
class SessionInfo:
    session_id: str
    agent_token: str
    user_token: str
    sfu_url: str


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

    async def start_session(self, avatar_id: str, session_id: str | None = None, voice_id: str | None = None) -> SessionInfo:
        body: dict[str, str] = {"avatarId": avatar_id}
        if session_id:
            body["sessionId"] = session_id
        if voice_id:
            body["voiceId"] = voice_id

        resp = await self._client.post(
            f"{self._base_url}/v1/session/start",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        data: dict = resp.json()

        if data.get("code") != 0:
            raise ApiError(data.get("code"), data.get("message", "unknown error"))

        d = data.get("data")
        if not d:
            raise ApiError(0, "response missing 'data' field")

        session_id_val = d.get("sessionId") or ""
        sfu_url_val = d.get("sfuUrl") or ""
        if not session_id_val or not sfu_url_val:
            raise ApiError(0, "response missing required fields: sessionId or sfuUrl")

        return SessionInfo(
            session_id=session_id_val,
            agent_token=d.get("agentToken", ""),
            user_token=d.get("userToken", ""),
            sfu_url=sfu_url_val,
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
            raise ApiError(
                data.get("code", -1), data.get("message", "unknown error")
            )


class ApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"API error {code}: {message}")
