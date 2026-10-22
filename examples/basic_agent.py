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

# Call examples. Nothing below runs.
#
# client = PlatformRTCClient(
#     api_key=os.environ["LIVEAVATAR_API_KEY"],
#     avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
#     base_url=os.environ.get("LIVEAVATAR_BASE_URL"),
#     input_sample_rate=16000,
#     output_sample_rate=24000,
#     sandbox=False,
#     external_audio_config={"sampleRate": 48000, "channels": 2},
# )
# Omit external_audio_config to follow the session voice format.
# A non-zero sampleRate must be 16000, 24000, 44100, or 48000. channels is 1 or 2.
# async with client as session:
#     session.frontend_connection  # user token and SFU URL only
#     session.is_agent_connected
#     session.is_user_joined
#     session.is_user_audio_subscribed
#     session.is_scene_ready
#     session.is_closing
#     session.is_closed
#     @session.on("user_audio_frame")
#     async def on_user_audio(frame): ...
#     @session.on("interrupted")
#     async def on_interrupted(request_id): ...
#     @session.on("disconnected")
#     async def on_disconnected(reason): ...
#     await session.wait_for_user(timeout=30)
#     await session.wait_for_user_audio(timeout=30)
#     await session.wait_for_scene_ready(timeout=30)
#     await session.publish_audio(AudioFrame.from_pcm(voice_pcm, sample_rate=24000))
#     await session.publish_audio_stream(tts_frames())  # this drives lip sync
#     await session.send_voice_start(request_id)
#     await session.send_asr_partial(request_id, "partial", seq=1)
#     await session.send_voice_finish(request_id)
#     await session.send_asr_final(request_id, "final text")
#     await session.send_custom_event("scene.switchVideo", {
#         "onceVideos": ["fist_bump"],  # resourceId or alias
#         "loopVideos": ["01KTJNMD7NZJF4KMGCCFSTJN4X"],
#     })
#     pcm = b"\x00" * 38400  # 200 ms, 48000 Hz, stereo, 16-bit
#     The PCM rate and channel count must match external_audio_config when set.
#     If it is omitted, match the session TTS audio format.
#     RTC base64-encodes the frame, so keep the PCM at or below 48000 bytes.
#     Send the next packet before the previous audio finishes playing.
#     The first packet may be longer than later packets, but not over that limit.
#     await session.publish_external_audio(pcm)
#     await session.publish_external_audio(pcm, timestamp_us=0)
#     Platform TTS song. This is the voice turn, not accompaniment.
#     song_pcm is 24000 Hz, mono, 16-bit raw PCM. Do not add a WebSocket frame header.
#     The SDK does not resample.
#     song = AudioFrame.from_pcm(song_pcm, 24000)
#     async def song_frames():
#         yield song
#     await session.send_external_playback(request_id, response_id, song_frames())
#     Sends response.audio.start and response.audio.finish with data.purpose=external.
#     interrupt adds the string parameter interrupt_scope.
#     await session.interrupt()  # VOICE_ONLY: stop voice and cancel the local voice stream
#     await session.interrupt(interrupt_scope="VOICE_ONLY")
#     await session.interrupt(interrupt_scope="BGM_ONLY")  # external audio only; local voice keeps running
#     await session.interrupt(interrupt_scope="VOICE_AND_ACCOMPANIMENT")
#     The value is sent as data.interruptScope on control.interrupt.
#     await session.close()
# await client.disconnect()
