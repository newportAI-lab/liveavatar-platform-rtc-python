import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import numpy as np
import pytest

from liveavatar_rtc.event_dispatcher import EventDispatcher
from liveavatar_rtc.session import (
    DISCONNECTED,
    ERROR,
    IDLE_TRIGGER,
    INPUT_TEXT,
    SCENE_READY,
    SESSION_CLOSING,
    SESSION_STATE,
    USER_AUDIO_FRAME,
    USER_AUDIO_TRACK_SUBSCRIBED,
    USER_JOINED,
    Session,
)
from liveavatar_rtc.types import AudioFrame, AudioTrackInfo, TTSConfig


@pytest.fixture
def mock_lk():
    """Create a mock LiveKitManager."""
    lk = MagicMock()
    type(lk).session_id = PropertyMock(return_value="sess-test-123")
    type(lk).sfu_url = PropertyMock(return_value="wss://sfu.test.com")
    type(lk).user_token = PropertyMock(return_value="user-tok-test")
    lk.events = EventDispatcher()
    lk.publish_audio_frame = AsyncMock()
    lk.send_data = AsyncMock()
    lk.wait_until_ready = AsyncMock()
    lk.disconnect = AsyncMock()
    return lk


@pytest.fixture
def session(mock_lk):
    return Session(mock_lk)


class TestSessionInit:
    def test_session_id_from_lk_manager(self, session, mock_lk):
        assert session.session_id == "sess-test-123"

    def test_sfu_url_from_lk_manager(self, session, mock_lk):
        assert session.sfu_url == "wss://sfu.test.com"

    def test_user_token_from_lk_manager(self, session, mock_lk):
        assert session.user_token == "user-tok-test"


class TestSessionEventBridge:
    @pytest.mark.asyncio
    async def test_user_audio_frame_bridged(self, session, mock_lk):
        received = []

        @session.on(USER_AUDIO_FRAME)
        async def handler(frame):
            received.append(frame)

        frame = AudioFrame(
            data=np.array([1, 2], dtype=np.int16),
            sample_rate=16000,
            num_channels=1,
        )
        await mock_lk.events.dispatch("user_audio_frame", frame)
        assert len(received) == 1
        assert received[0] is frame

    @pytest.mark.asyncio
    async def test_user_audio_track_subscribed_bridged(self, session, mock_lk):
        received = []

        @session.on(USER_AUDIO_TRACK_SUBSCRIBED)
        async def handler(info):
            received.append(info)

        info = AudioTrackInfo(
            sample_rate=16000,
            num_channels=1,
            participant_identity="user_bob",
            track_sid="TR_xyz",
        )
        await mock_lk.events.dispatch("user_audio_track_subscribed", info)
        assert received == [info]

    @pytest.mark.asyncio
    async def test_user_joined_bridged(self, session, mock_lk):
        received = []

        @session.on(USER_JOINED)
        async def handler(identity):
            received.append(identity)

        await mock_lk.events.dispatch("user_joined", "user_alice")
        assert received == ["user_alice"]

    @pytest.mark.asyncio
    async def test_disconnected_bridged(self, session, mock_lk):
        received = []

        @session.on(DISCONNECTED)
        async def handler(reason):
            received.append(reason)

        await mock_lk.events.dispatch("disconnected", "user_left")
        assert received == ["user_left"]

    @pytest.mark.asyncio
    async def test_input_text_bridged(self, session, mock_lk):
        received = []

        @session.on(INPUT_TEXT)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(INPUT_TEXT, {"text": "hello", "requestId": "r1"})
        assert received == [{"text": "hello", "requestId": "r1"}]

    @pytest.mark.asyncio
    async def test_scene_ready_bridged(self, session, mock_lk):
        received = []

        @session.on(SCENE_READY)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(SCENE_READY, {"status": "ready"})
        assert received == [{"status": "ready"}]

    @pytest.mark.asyncio
    async def test_session_state_bridged(self, session, mock_lk):
        received = []

        @session.on(SESSION_STATE)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(SESSION_STATE, {"state": "SPEAKING"})
        assert received == [{"state": "SPEAKING"}]

    @pytest.mark.asyncio
    async def test_session_closing_bridged(self, session, mock_lk):
        received = []

        @session.on(SESSION_CLOSING)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(SESSION_CLOSING, {"reason": "timeout"})
        assert received == [{"reason": "timeout"}]

    @pytest.mark.asyncio
    async def test_idle_trigger_bridged(self, session, mock_lk):
        received = []

        @session.on(IDLE_TRIGGER)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(IDLE_TRIGGER, {"since_ms": 5000})
        assert received == [{"since_ms": 5000}]

    @pytest.mark.asyncio
    async def test_error_bridged(self, session, mock_lk):
        received = []

        @session.on(ERROR)
        async def handler(data):
            received.append(data)

        await mock_lk.events.dispatch(ERROR, {"code": "500", "message": "fail"})
        assert received == [{"code": "500", "message": "fail"}]


class TestSessionPublishAudio:
    @pytest.mark.asyncio
    async def test_delegates_to_lk_manager(self, session, mock_lk):
        frame = AudioFrame(
            data=np.array([0], dtype=np.int16), sample_rate=16000, num_channels=1
        )
        await session.publish_audio(frame)
        mock_lk.publish_audio_frame.assert_called_once_with(frame)


class TestSessionPlatformTTS:
    @pytest.mark.asyncio
    async def test_send_response_start_defaults(self, session, mock_lk):
        with patch("uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
            request_id = await session.send_response_start()

        assert request_id == "12345678-1234-5678-1234-567812345678"
        mock_lk.send_data.assert_called_once_with(
            "response.start", {"requestId": request_id}
        )

    @pytest.mark.asyncio
    async def test_send_response_start_with_config(self, session, mock_lk):
        cfg = TTSConfig(speed=1.5, volume=0.8, mood="cheerful")
        with patch("uuid.uuid4", return_value=uuid.UUID("87654321-4321-8765-4321-876543218765")):
            request_id = await session.send_response_start(cfg)

        mock_lk.send_data.assert_called_once_with(
            "response.start",
            {"requestId": request_id, "speed": 1.5, "volume": 0.8, "mood": "cheerful"},
        )

    @pytest.mark.asyncio
    async def test_send_response_start_partial_config(self, session, mock_lk):
        cfg = TTSConfig(speed=1.2, mood=None)
        with patch("uuid.uuid4", return_value=uuid.UUID("00000000-0000-0000-0000-000000000001")):
            await session.send_response_start(cfg)

        payload = mock_lk.send_data.call_args[0][1]
        assert "speed" in payload
        assert "volume" not in payload
        assert "mood" not in payload

    @pytest.mark.asyncio
    async def test_send_response_chunk_buffered_by_text_chunker(self, session, mock_lk):
        """send_response_chunk buffers text; only sends complete sentences."""
        await session.send_response_chunk("req-1", "Based on data,")
        # No terminator — nothing sent yet
        mock_lk.send_data.assert_not_called()

        await session.send_response_chunk("req-1", " it is volatile.")
        # Now the accumulated text has a period — flush should fire
        await asyncio.sleep(0)
        calls = [c for c in mock_lk.send_data.call_args_list
                 if c[0][0] == "response.chunk"]
        assert len(calls) >= 1
        assert "volatile." in calls[0][0][1]["text"]

    @pytest.mark.asyncio
    async def test_send_response_chunk_strips_markdown(self, session, mock_lk):
        """TextChunker inside send_response_chunk strips markdown."""
        await session.send_response_chunk(
            "req-3", "Output: ```python\nprint('hi')\n```\nIt works."
        )
        await session.send_response_done("req-3")
        await asyncio.sleep(0)

        calls = mock_lk.send_data.call_args_list
        chunk_calls = [c for c in calls if c[0][0] == "response.chunk"]
        for call in chunk_calls:
            assert "print" not in call[0][1]["text"]

    @pytest.mark.asyncio
    async def test_send_response_done_flushes_remaining(self, session, mock_lk):
        """send_response_done flushes buffered text before done signal."""
        await session.send_response_chunk("req-1", "Unfinished text")
        await session.send_response_done("req-1")

        calls = mock_lk.send_data.call_args_list
        # response.chunk (buffered flush) comes before response.done
        assert len(calls) >= 2
        assert calls[-1][0][0] == "response.done"
        assert calls[-2][0][0] == "response.chunk"

    @pytest.mark.asyncio
    async def test_send_response_done_no_chunker(self, session, mock_lk):
        """send_response_done with no prior chunks still sends done."""
        await session.send_response_done("req-1")
        mock_lk.send_data.assert_called_once_with(
            "response.done", {"requestId": "req-1"}
        )

    @pytest.mark.asyncio
    async def test_send_response_cancel_discards_buffer(self, session, mock_lk):
        """send_response_cancel discards buffered text."""
        await session.send_response_chunk("req-1", "Discarded text")
        await session.send_response_cancel("req-1")

        # Only response.cancel should have been sent, no response.chunk
        mock_lk.send_data.assert_called_once()
        assert mock_lk.send_data.call_args[0][0] == "response.cancel"


class TestSessionSubtitle:
    @pytest.mark.asyncio
    async def test_send_subtitle(self, session, mock_lk):
        await session.send_subtitle("req-1", "Subtitle text")
        mock_lk.send_data.assert_called_once_with(
            "response.chunk", {"requestId": "req-1", "text": "Subtitle text"}
        )


class TestSessionControl:
    @pytest.mark.asyncio
    async def test_interrupt(self, session, mock_lk):
        await session.interrupt()
        mock_lk.send_data.assert_called_once_with("control.interrupt")

    @pytest.mark.asyncio
    async def test_send_prompt(self, session, mock_lk):
        await session.send_prompt("Hello, how are you?")
        mock_lk.send_data.assert_called_once_with(
            "system.prompt", {"text": "Hello, how are you?"}
        )


class TestSessionResponseCancel:
    @pytest.mark.asyncio
    async def test_send_response_cancel(self, session, mock_lk):
        await session.send_response_cancel("req-1")
        mock_lk.send_data.assert_called_once_with(
            "response.cancel", {"requestId": "req-1"}
        )


class TestSessionDeveloperTTS:
    @pytest.mark.asyncio
    async def test_send_response_audio_start(self, session, mock_lk):
        with patch("uuid.uuid4", return_value=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")):
            request_id = await session.send_response_audio_start()

        assert request_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        mock_lk.send_data.assert_called_once_with(
            "response.audio.start", {"requestId": request_id}
        )

    @pytest.mark.asyncio
    async def test_send_response_audio_finish(self, session, mock_lk):
        await session.send_response_audio_finish("req-1")
        mock_lk.send_data.assert_called_once_with(
            "response.audio.finish", {"requestId": "req-1"}
        )

    @pytest.mark.asyncio
    async def test_send_response_audio_prompt_start(self, session, mock_lk):
        with patch("uuid.uuid4", return_value=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")):
            request_id = await session.send_response_audio_prompt_start()

        assert request_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        mock_lk.send_data.assert_called_once_with(
            "response.audio.promptStart", {"requestId": request_id}
        )

    @pytest.mark.asyncio
    async def test_send_response_audio_prompt_finish(self, session, mock_lk):
        await session.send_response_audio_prompt_finish("req-1")
        mock_lk.send_data.assert_called_once_with(
            "response.audio.promptFinish", {"requestId": "req-1"}
        )


class TestSessionDeveloperASR:
    @pytest.mark.asyncio
    async def test_send_asr_partial(self, session, mock_lk):
        await session.send_asr_partial("partial text")
        mock_lk.send_data.assert_called_once_with(
            "input.asr.partial", {"text": "partial text"}
        )

    @pytest.mark.asyncio
    async def test_send_asr_final(self, session, mock_lk):
        await session.send_asr_final("final text")
        mock_lk.send_data.assert_called_once_with(
            "input.asr.final", {"text": "final text"}
        )


class TestSessionDeveloperVAD:
    @pytest.mark.asyncio
    async def test_send_voice_start(self, session, mock_lk):
        await session.send_voice_start()
        mock_lk.send_data.assert_called_once_with("input.voice.start")

    @pytest.mark.asyncio
    async def test_send_voice_finish(self, session, mock_lk):
        await session.send_voice_finish()
        mock_lk.send_data.assert_called_once_with("input.voice.finish")


class TestSessionErrorReporting:
    @pytest.mark.asyncio
    async def test_send_error(self, session, mock_lk):
        await session.send_error("E001", "Something went wrong")
        mock_lk.send_data.assert_called_once_with(
            "error", {"code": "E001", "message": "Something went wrong"}
        )


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_wait_until_ready(self, session, mock_lk):
        await session.wait_until_ready(timeout=10.0)
        mock_lk.wait_until_ready.assert_called_once_with(10.0)

    @pytest.mark.asyncio
    async def test_wait_until_ready_default_timeout(self, session, mock_lk):
        await session.wait_until_ready()
        mock_lk.wait_until_ready.assert_called_once_with(30.0)

    @pytest.mark.asyncio
    async def test_close(self, session, mock_lk):
        await session.close()
        mock_lk.disconnect.assert_called_once()
