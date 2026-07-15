import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

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
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
    ) -> None:
        self._session_id = session_id
        self._sfu_url = sfu_url
        self._agent_token = agent_token
        self._user_token = user_token
        self._input_sample_rate = input_sample_rate
        self._output_sample_rate = output_sample_rate

        self._room = rtc.Room()
        self._audio_source: rtc.AudioSource | None = None
        self._audio_track: rtc.LocalAudioTrack | None = None
        self._audio_streams: dict[str, rtc.AudioStream] = {}
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._user_audio_stream: rtc.AudioStream | None = None
        self._user_audio_task: asyncio.Task | None = None
        self._user_audio_track_sid: str | None = None
        self._user_audio_lock = asyncio.Lock()
        self._room_event_tasks: set[asyncio.Task] = set()
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
            sample_rate=self._output_sample_rate, num_channels=1, queue_size_ms=200
        )
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "agent_audio", self._audio_source
        )
        await self._room.local_participant.publish_track(self._audio_track)
        logger.info("LiveKit connected, agent audio track published")

    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)

    async def disconnect(self) -> None:
        async with self._user_audio_lock:
            await self._clear_user_audio()
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
        handlers = {
            "connected": self._on_connected,
            "disconnected": self._on_disconnected,
            "reconnecting": self._on_reconnecting,
            "reconnected": self._on_reconnected,
            "track_subscribed": self._on_track_subscribed,
            "track_unsubscribed": self._on_track_unsubscribed,
            "data_received": self._on_data_received,
            "participant_connected": self._on_participant_connected,
            "participant_disconnected": self._on_participant_disconnected,
            "track_muted": self._on_track_muted,
            "track_unmuted": self._on_track_unmuted,
            "connection_quality_changed": self._on_connection_quality_changed,
        }
        for event, handler in handlers.items():
            self._room.on(event, self._schedule_room_handler(handler))

    def _schedule_room_handler(
        self, handler: Callable[..., Awaitable[None]]
    ) -> Callable[..., None]:
        def callback(*args: Any) -> None:
            task = asyncio.create_task(handler(*args))
            self._room_event_tasks.add(task)
            task.add_done_callback(self._room_event_tasks.discard)

        return callback

    async def _on_connected(self) -> None:
        logger.debug("LiveKit room connected")

    async def _on_disconnected(self, reason: rtc.DisconnectReason) -> None:
        await self.events.dispatch("disconnected", str(reason))

    async def _on_reconnecting(self) -> None:
        logger.info("LiveKit reconnecting...")
        await self.events.dispatch("reconnecting")

    async def _on_reconnected(self) -> None:
        await self.events.dispatch("reconnected")

    def _is_user_identity(self, identity: str) -> bool:
        return identity.startswith("user")

    def _participant_role(self, identity: str) -> str | None:
        if self._is_user_identity(identity):
            return "user"
        if identity == f"coordinator_{self._session_id}":
            return "coordinator"
        if identity == f"renderer_{self._session_id}":
            return "renderer"
        return None

    async def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        role = self._participant_role(participant.identity)
        if role == "user":
            self._ready_event.set()
        if role:
            await self.events.dispatch(f"{role}_joined", participant.identity)

    async def _on_participant_disconnected(
        self, participant: rtc.RemoteParticipant
    ) -> None:
        role = self._participant_role(participant.identity)
        if role:
            await self.events.dispatch(f"{role}_left", participant.identity)

    async def _on_connection_quality_changed(
        self, participant: rtc.Participant, quality: rtc.ConnectionQuality
    ) -> None:
        await self.events.dispatch(
            "connection_quality_changed", participant.identity, quality
        )

    async def _on_track_muted(
        self, participant: rtc.Participant, publication: rtc.TrackPublication
    ) -> None:
        if self._is_user_identity(participant.identity):
            await self.events.dispatch("user_audio_track_muted", publication.sid)

    async def _on_track_unmuted(
        self, participant: rtc.Participant, publication: rtc.TrackPublication
    ) -> None:
        if self._is_user_identity(participant.identity):
            await self.events.dispatch("user_audio_track_unmuted", publication.sid)

    async def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if not isinstance(track, rtc.RemoteAudioTrack):
            return
        if not self._is_user_identity(participant.identity):
            return
        source = getattr(publication, "source", None)
        if source is not None and source != rtc.TrackSource.SOURCE_MICROPHONE:
            return

        logger.info(
            "Subscribed to user audio: identity=%s sid=%s",
            participant.identity,
            track.sid,
        )

        async with self._user_audio_lock:
            await self._clear_user_audio()
            stream = rtc.AudioStream(
                track,
                sample_rate=self._input_sample_rate,
                num_channels=1,
            )
            self._user_audio_stream = stream
            self._user_audio_track_sid = track.sid
            self._audio_streams[track.sid] = stream

            info = AudioTrackInfo(
                sample_rate=self._input_sample_rate,
                num_channels=1,
                participant_identity=participant.identity,
                track_sid=track.sid,
            )
            await self.events.dispatch("user_audio_track_subscribed", info)

            task = asyncio.create_task(self._consume_audio_stream(track.sid, stream))
            self._user_audio_task = task
            self._stream_tasks[track.sid] = task

    async def _clear_user_audio(self) -> None:
        task = self._user_audio_task
        stream = self._user_audio_stream
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if stream is not None:
            await stream.aclose()
        self._audio_streams.clear()
        self._stream_tasks.clear()
        self._user_audio_stream = None
        self._user_audio_task = None
        self._user_audio_track_sid = None

    async def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        async with self._user_audio_lock:
            if track.sid == self._user_audio_track_sid:
                await self._clear_user_audio()

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
                    timestamp=lk_frame.timestamp_us,
                )
                await self.events.dispatch("user_audio_frame", audio_frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error consuming audio stream %s", track_sid)
