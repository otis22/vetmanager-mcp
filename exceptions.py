class VetmanagerError(Exception):
    """Base exception for all Vetmanager API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(VetmanagerError):
    """Invalid or missing API key."""


class NotFoundError(VetmanagerError):
    """Requested resource does not exist."""


class VetmanagerTimeoutError(VetmanagerError):
    """Request to Vetmanager API timed out."""


class HostResolutionError(VetmanagerError):
    """Failed to resolve Vetmanager host for the given domain."""
