import asyncio
import json
import logging

import numpy as np
from livekit import rtc

from .event_dispatcher import EventDispatcher
from .types import AudioFrame, AudioTrackInfo

logger = logging.getLogger(__name__)

DATA_TOPIC = "liveavatar"


class LiveKitManager:
    """LiveKit Room + Track + Data Channel management for agent_{sessionId}."""

    def __init__(
        self,
        session_id: str,
        sfu_url: str,
        agent_token: str,
        user_token: str = "",
        sample_rate: int = 16000,
    ) -> None:
        self._session_id = session_id
        self._sfu_url = sfu_url
        self._agent_token = agent_token
        self._user_token = user_token
        self._sample_rate = sample_rate

        self._room = rtc.Room()
        self._audio_source: rtc.AudioSource | None = None
        self._audio_track: rtc.LocalAudioTrack | None = None
        self._audio_streams: dict[str, rtc.AudioStream] = {}
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._ready_event = asyncio.Event()

        self.events = EventDispatcher()

        self._setup_room_events()

    @property
    def room(self) -> rtc.Room:
        return self._room

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def sfu_url(self) -> str:
        return self._sfu_url

    @property
    def user_token(self) -> str:
        return self._user_token

    @property
    def identity(self) -> str:
        return f"agent_{self._session_id}"

    # ── Connection ──────────────────────────────────────────

    async def connect(self) -> None:
        logger.info("Connecting to LiveKit: url=%s identity=%s", self._sfu_url, self.identity)
        await self._room.connect(self._sfu_url, self._agent_token)
        self._audio_source = rtc.AudioSource(
            sample_rate=self._sample_rate, num_channels=1, queue_size_ms=200
        )
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "agent_audio", self._audio_source
        )
        await self._room.local_participant.publish_track(self._audio_track)
        logger.info("LiveKit connected, agent audio track published")

    async def wait_until_ready(self, timeout: float = 3000.0) -> None:
        await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)

    async def disconnect(self) -> None:
        tasks = list(self._stream_tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Error awaiting cancelled task", exc_info=True)
        self._stream_tasks.clear()
        self._audio_streams.clear()
        if self._audio_source:
            await self._audio_source.aclose()
        await self._room.disconnect()
        logger.info("LiveKit disconnected")

    # ── Audio Publishing ────────────────────────────────────

    async def publish_audio_frame(self, frame: AudioFrame) -> None:
        if self._audio_source is None:
            logger.warning("publish_audio_frame called before connect; frame dropped")
            return
        lk_frame = rtc.AudioFrame.create(
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=len(frame.data),
        )
        lk_data = lk_frame.data
        if isinstance(lk_data, memoryview):
            lk_data = lk_data.cast("b")
        target = np.frombuffer(lk_data, dtype=np.int16)
        n = min(len(target), len(frame.data))
        target[:n] = frame.data[:n]
        await self._audio_source.capture_frame(lk_frame)

    # ── Data Channel ────────────────────────────────────────

    async def send_data(self, event: str, data: dict | None = None) -> None:
        payload = json.dumps({"event": event, "data": data or {}})
        await self._room.local_participant.publish_data(
            payload, reliable=True, topic=DATA_TOPIC
        )

    # ── Internal Events ─────────────────────────────────────

    def _setup_room_events(self) -> None:
        # Use sync callbacks with asyncio.create_task() — LiveKit's Room
        # does not support async callbacks registered via .on()
        self._room.on("connected", lambda *args: asyncio.create_task(self._on_connected(*args)))
        self._room.on("disconnected", lambda *args: asyncio.create_task(self._on_disconnected(*args)))
        self._room.on("reconnecting", self._on_reconnecting)
        self._room.on("track_subscribed", lambda *args: asyncio.create_task(self._on_track_subscribed(*args)))
        self._room.on("track_unsubscribed", self._on_track_unsubscribed)
        self._room.on("data_received", lambda *args: asyncio.create_task(self._on_data_received(*args)))
        self._room.on("participant_connected", lambda *args: asyncio.create_task(self._on_participant_connected(*args)))

    async def _on_connected(self) -> None:
        logger.debug("LiveKit room connected")

    async def _on_disconnected(self, reason: rtc.DisconnectReason) -> None:
        await self.events.dispatch("disconnected", str(reason))

    def _on_reconnecting(self) -> None:
        logger.info("LiveKit reconnecting...")

    async def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity.startswith("user"):
            self._ready_event.set()
            await self.events.dispatch("user_joined", participant.identity)

    async def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if not isinstance(track, rtc.RemoteAudioTrack):
            return
        if not participant.identity.startswith("user"):
            return

        logger.info(
            "Subscribed to user audio: identity=%s sid=%s",
            participant.identity,
            track.sid,
        )

        stream = rtc.AudioStream(
            track,
            sample_rate=self._sample_rate,
            num_channels=1,
        )
        self._audio_streams[track.sid] = stream

        info = AudioTrackInfo(
            sample_rate=self._sample_rate,
            num_channels=1,
            participant_identity=participant.identity,
            track_sid=track.sid,
        )
        await self.events.dispatch("user_audio_track_subscribed", info)

        task = asyncio.create_task(self._consume_audio_stream(track.sid, stream))
        self._stream_tasks[track.sid] = task

    def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.sid in self._audio_streams:
            del self._audio_streams[track.sid]
        if track.sid in self._stream_tasks:
            self._stream_tasks[track.sid].cancel()
            del self._stream_tasks[track.sid]

    async def _on_data_received(self, packet: rtc.DataPacket) -> None:
        try:
            msg = json.loads(packet.data)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON data channel message: %r", packet.data)
            return

        event = msg.get("event", "")
        data = msg.get("data", {})
        await self.events.dispatch(event, data)

    async def _consume_audio_stream(self, track_sid: str, stream: rtc.AudioStream) -> None:
        try:
            async for frame_event in stream:
                lk_frame = frame_event.frame
                lk_data = lk_frame.data
                if isinstance(lk_data, memoryview):
                    arr = np.frombuffer(lk_data, dtype=np.int16).copy()
                else:
                    arr = np.array(lk_data, dtype=np.int16)

                audio_frame = AudioFrame(
                    data=arr,
                    sample_rate=lk_frame.sample_rate,
                    num_channels=lk_frame.num_channels,
                    timestamp=getattr(lk_frame, "timestamp", 0),
                )
                await self.events.dispatch("user_audio_frame", audio_frame)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error consuming audio stream %s", track_sid)
