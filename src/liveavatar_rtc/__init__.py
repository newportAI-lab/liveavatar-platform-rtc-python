from importlib.metadata import PackageNotFoundError, version

from .errors import (
    APIError,
    AudioFormatError,
    AudioPublishError,
    DataChannelProtocolError,
    RTCConnectionError,
    RTCSDKError,
    SessionClosedError,
    SessionStartError,
    SessionWaitTimeoutError,
)
from .client import PlatformRTCClient
from .session import (
    CUSTOM_EVENT,
    DISCONNECTED,
    ERROR,
    IDLE_TRIGGER,
    SCENE_RESOURCE_TRANSITION,
    SCENE_READY,
    SESSION_CLOSING,
    SESSION_STATE,
    USER_AUDIO_FRAME,
    USER_AUDIO_TRACK_SUBSCRIBED,
    USER_AUDIO_TRACK_UNSUBSCRIBED,
    USER_JOINED,
    USER_LEFT,
    Session,
)
from .types import (
    AudioFrame,
    AudioTrackInfo,
    DataChannelEvent,
    FrontendConnection,
    SessionInfo,
)

try:
    __version__ = version("liveavatar-platform-rtc")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    "RTCSDKError",
    "APIError",
    "SessionStartError",
    "RTCConnectionError",
    "SessionClosedError",
    "SessionWaitTimeoutError",
    "AudioFormatError",
    "AudioPublishError",
    "DataChannelProtocolError",
    "FrontendConnection",
    "SessionInfo",
    "DataChannelEvent",
    "AudioFrame",
    "AudioTrackInfo",
    "PlatformRTCClient",
    "Session",
    "SCENE_READY",
    "SCENE_RESOURCE_TRANSITION",
    "SESSION_STATE",
    "SESSION_CLOSING",
    "IDLE_TRIGGER",
    "ERROR",
    "CUSTOM_EVENT",
    "USER_AUDIO_FRAME",
    "USER_AUDIO_TRACK_SUBSCRIBED",
    "USER_AUDIO_TRACK_UNSUBSCRIBED",
    "USER_JOINED",
    "USER_LEFT",
    "DISCONNECTED",
]
