"""Reject new HTTP writes while a worker is quiescing for shutdown."""

from shutdown_state import admit_write, finish_write


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class WriteAdmissionMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("method") in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if not admit_write():
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"application/json"), (b"retry-after", b"5")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error":"worker_draining","retryable":true}',
            })
            return
        try:
            await self.app(scope, receive, send)
        finally:
            finish_write()
