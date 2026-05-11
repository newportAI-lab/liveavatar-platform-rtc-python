"""
Basic Agent Example — Platform RTC Python SDK

This is a skeleton showing the minimal flow. Replace the TODOs with your actual
ASR / LLM / TTS implementations.

Prerequisites:
    export LIVEAVATAR_API_KEY="lf_..."

Usage:
    python examples/basic_agent.py
"""

import asyncio
import json
import os

from liveavatar_rtc import (
    PlatformRTCClient,
    AudioFrame,
    USER_AUDIO_FRAME,
    INPUT_TEXT,
    SESSION_STATE,
    SCENE_READY,
    DISCONNECTED,
)


class BasicAgent:
    def __init__(self, api_key: str, avatar_id: str, base_url: str | None = None):
        self.client = PlatformRTCClient(
            api_key=api_key,
            avatar_id=avatar_id,
            base_url=base_url,
            # sample_rate=16000,  # default
            # sandbox=True,       # uncomment for sandbox
        )

    async def run(self):
        async with self.client as session:
            self._register_handlers(session)
            await session.wait_until_ready()
            print(f"Agent ready, session={session.session_id}")
            print(f"Frontend handoff: sessionId={session.session_id} userToken={session.user_token} sfuUrl={session.sfu_url}")

            # TODO: pass session.session_id, session.user_token, session.sfu_url
            # to your frontend so the user can join the same LiveKit room.

            # Keep running until disconnected
            disconnect_event = asyncio.Event()

            @session.on(DISCONNECTED)
            async def on_disconnect(reason):
                print(f"Disconnected: {reason}")
                disconnect_event.set()

            await disconnect_event.wait()

    def _register_handlers(self, session):
        @session.on(SCENE_READY)
        async def on_scene_ready(data: dict):
            print(f"Scene ready: {data}")

        @session.on(USER_AUDIO_FRAME)
        async def on_audio(frame: AudioFrame):
            # Echo back the received audio
            print(f"Audio received, frame={frame}")
            session.publish_audio(frame)
        @session.on(INPUT_TEXT)
        async def on_text(data: dict):
            data_str = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            print(data_str)
            text = data.get("text", "")
            # TODO: LLM(text) → reply → TTS → publish_audio
            await session.send_response_chunk('343242', text)

        @session.on(SESSION_STATE)
        async def on_state(data: dict):
            state = data.get("state", "")
            print(f"State: {state}")


if __name__ == "__main__":
    api_key = os.environ.get("LIVEAVATAR_API_KEY", "lk_live_ohaq3--lMzUlITsFL98wtackS_tn6O1nHIyIK0I4k14")
    avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "2")
    base_url = os.environ.get("LIVEAVATAR_BASE_URL")  # None = use default

    if not api_key:
        print("Set LIVEAVATAR_API_KEY environment variable")
        exit(1)

    agent = BasicAgent(api_key=api_key, avatar_id=avatar_id, base_url=base_url)
    asyncio.run(agent.run())
