class RTCSDKError(Exception):
    """Base exception for the RTC Agent SDK."""


class APIError(RTCSDKError):
    def __init__(self, code: int | str | None, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"API error {code}: {message}")


class SessionStartError(RTCSDKError):
    pass


class RTCConnectionError(RTCSDKError):
    pass


class SessionClosedError(RTCSDKError):
    pass


class SessionWaitTimeoutError(RTCSDKError):
    pass


class AudioFormatError(RTCSDKError):
    pass


class AudioPublishError(RTCSDKError):
    pass


class DataChannelProtocolError(RTCSDKError):
    pass
