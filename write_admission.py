"""Reject new HTTP writes while a worker is quiescing for shutdown."""

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from shutdown_state import admit_write, finish_write


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ExecutionAdmissionMiddleware(Middleware):
    """Keep tool execution counted after its HTTP response disconnects."""

    async def on_call_tool(self, context, call_next):
        if not admit_write():
            raise ToolError("Worker is draining; reconnect and retry after checking the operation outcome.")
        try:
            return await call_next(context)
        finally:
            finish_write()


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
