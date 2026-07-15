"""Minimal Platform RTC agent with a developer-owned ASR/LLM/TTS pipeline.

This provider-free skeleton connects and consumes user audio, but intentionally
produces no avatar speech until you integrate real developer ASR/LLM/TTS.
"""

import asyncio
import os
from collections.abc import AsyncIterator

from liveavatar_rtc import AudioFrame, DISCONNECTED, PlatformRTCClient


async def developer_pipeline(
    input_audio: asyncio.Queue[AudioFrame],
) -> AsyncIterator[AudioFrame]:
    """Replace with ASR (16 kHz PCM) -> LLM -> TTS (24 kHz PCM)."""
    while True:
        await input_audio.get()
        # A real implementation yields mono PCM16 TTS frames, for example:
        # yield AudioFrame.from_pcm(tts_pcm, sample_rate=24000)
        if False:  # Keeps this no-provider example an async generator.
            yield AudioFrame.from_pcm(b"", sample_rate=24000)


async def main() -> None:
    print(
        "WARNING: provider-free demo consumes user audio but produces no avatar "
        "speech; integrate developer ASR/LLM/TTS to enable responses."
    )
    client = PlatformRTCClient(
        api_key=os.environ["LIVEAVATAR_API_KEY"],
        avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
        input_sample_rate=16000,
        output_sample_rate=24000,
        base_url=os.environ.get("LIVEAVATAR_BASE_URL"),
    )

    # Stage 1: connect the backend agent to the Platform RTC room.
    async with client as session:
        # Send only this user credential and SFU URL to your frontend. Never
        # expose the API key or the agent credential.
        print(f"frontend connection: {session.frontend_connection}")
        pipeline_input: asyncio.Queue[AudioFrame] = asyncio.Queue()
        disconnected = asyncio.Event()

        @session.on("user_audio_frame")
        async def on_user_audio(frame: AudioFrame) -> None:
            # Input is mono PCM16 resampled to 16 kHz for developer ASR/Omni.
            await pipeline_input.put(frame)

        @session.on("interrupted")
        async def on_interrupted(request_id: str | None) -> None:
            # Also cancel your current LLM/TTS generation for this turn.
            print(f"interrupted: {request_id}")

        @session.on(DISCONNECTED)
        async def on_disconnected(reason: str) -> None:
            print(f"disconnected: {reason}")
            disconnected.set()

        # Stage 2: wait for the frontend user to join the same room.
        await session.wait_for_user(timeout=30)
        # Stage 3: wait until the avatar scene can render streamed audio.
        await session.wait_for_scene_ready(timeout=30)

        # The SDK validates mono PCM16 and the negotiated output sample rate,
        # then LiveKit owns real-time buffering and Opus encoding.
        output_task = asyncio.create_task(
            session.publish_audio_stream(developer_pipeline(pipeline_input))
        )
        try:
            await disconnected.wait()
        finally:
            output_task.cancel()
            await asyncio.gather(output_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
