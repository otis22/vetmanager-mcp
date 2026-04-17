class VetmanagerError(Exception):
    """Base exception for all Vetmanager API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(VetmanagerError):
    """Invalid or missing API key."""


class RateLimitError(VetmanagerError):
    """Request frequency exceeded the configured safety limit."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = 429,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message, status_code=status_code)
        self.retry_after_seconds = retry_after_seconds


class NotFoundError(VetmanagerError):
    """Requested resource does not exist."""


class VetmanagerTimeoutError(VetmanagerError):
    """Request to Vetmanager API timed out."""


class HostResolutionError(VetmanagerError):
    """Failed to resolve Vetmanager host for the given domain."""


class VetmanagerUpstreamUnavailable(VetmanagerError):
    """Circuit breaker is open for this domain — upstream considered unhealthy.

    Tools catching VetmanagerError continue to catch this too (backwards-compatible).
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None):
        super().__init__(message, status_code=503)
        self.retry_after_seconds = retry_after_seconds
