from fastmcp.exceptions import ToolError


class VetmanagerError(Exception):
    """Base exception for all Vetmanager API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        error_code: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


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


class ToolInputError(ToolError):
    """The caller supplied something invalid — not a defect worth reporting.

    Stage 265.5: this distinction used to live in the wording of the message,
    which meant it broke the moment somebody improved the wording. It stays a
    ToolError so every existing handler keeps catching it.
    """


def reportable_error(*args: object) -> ToolError:
    """A failure the agent is invited to report: upstream, its payload, or us.

    Stage 265.6: inside `tools/` the pair `ToolInputError` / `reportable_error`
    replaces a bare `ToolError`, so every refusal says in its own line whose
    mistake it was. Returns the exact `ToolError` class on purpose — the
    privacy layer redacts by exact type (`type(exc) is ToolError`), and a
    subclass would quietly walk out from under it.
    """
    return ToolError(*args)
