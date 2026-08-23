import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn

from fastmcp import FastMCP

from agent_feedback_service import validate_feedback_runtime_config
from error_tracking import configure_error_tracking
from host_resolver import reset_billing_resolver
from observability_logging import RUNTIME_LOGGER
from rate_limit_backend import shutdown_rate_limit_backend
from storage import bootstrap_storage_schema, get_database_url, initialize_storage, shutdown_storage
from shutdown_state import begin_draining, reset_draining
from structured_logging import configure_logging
from tool_oauth_security import OAuthChallengeMiddleware, apply_tool_oauth_security_metadata
from tool_error_tracking import ToolErrorTrackingMiddleware
from tool_descriptions import enhance_tool_descriptions
from vetmanager_client import reset_breakers, reset_shared_http_client
from web import register_web_routes

SHUTDOWN_STEP_TIMEOUT_SECONDS = 3
STREAMABLE_HTTP_DRAIN_ENABLED_ENV = "STREAMABLE_HTTP_DRAIN_ENABLED"


def _log_startup_aborted(exc: Exception, *, step: str) -> None:
    RUNTIME_LOGGER.critical(
        "Startup aborted during %s: %s",
        step,
        exc,
        extra={"event_name": "startup_aborted", "step": step},
    )


def _run_startup_step(step: str, func):
    try:
        return func()
    except Exception as exc:
        _log_startup_aborted(exc, step=step)
        raise


def _load_runtime_config() -> tuple[str, str, int, str]:
    return (
        os.environ.get("MCP_TRANSPORT", "streamable-http"),
        os.environ.get("MCP_HOST", "0.0.0.0"),
        int(os.environ.get("PORT", "8000")),
        os.environ.get("MCP_PATH", "/mcp"),
    )


async def _close_step(name, operation) -> None:
    try:
        await asyncio.wait_for(operation(), timeout=SHUTDOWN_STEP_TIMEOUT_SECONDS)
    except Exception:
        RUNTIME_LOGGER.warning("Graceful shutdown error", extra={"event_name": "shutdown_error", "step": name}, exc_info=True)


async def _graceful_shutdown() -> None:
    await _close_step("shutdown_storage", shutdown_storage)
    await _close_step("reset_shared_http_client", reset_shared_http_client)
    await _close_step("reset_breakers", reset_breakers)
    await _close_step("reset_billing_resolver", reset_billing_resolver)
    await _close_step("shutdown_rate_limit_backend", shutdown_rate_limit_backend)


@asynccontextmanager
async def _runtime_lifespan(_server):
    reset_draining()
    try:
        await initialize_storage()
        if get_database_url().startswith("sqlite"):
            await bootstrap_storage_schema()
        yield
    finally:
        await _graceful_shutdown()


def _streamable_http_drain_enabled() -> bool:
    return os.environ.get(STREAMABLE_HTTP_DRAIN_ENABLED_ENV, "true").lower() not in {"0", "false", "no"}


def _get_streamable_session_manager(app, *, path: str):
    """Return the FastMCP streamable-session manager owned by this HTTP app."""
    route = next((route for route in app.routes if getattr(route, "path", None) == path), None)
    endpoints = [getattr(route, "endpoint", None)]
    manager = None
    seen = set()
    for _ in range(12):
        if not endpoints:
            break
        endpoint = endpoints.pop()
        if endpoint is None or id(endpoint) in seen:
            continue
        seen.add(id(endpoint))
        manager = getattr(endpoint, "session_manager", None)
        if manager is not None:
            break
        endpoints.extend(
            value
            for value in vars(endpoint).values() if value is not endpoint
        ) if hasattr(endpoint, "__dict__") else None
        endpoints.extend(getattr(endpoint, attribute, None) for attribute in ("app", "endpoint", "__wrapped__", "func"))
    if manager is None:
        RUNTIME_LOGGER.error(
            "Streamable HTTP drain is unavailable",
            extra={"event_name": "streamable_http_drain_unsupported"},
        )
    return manager


def _close_standalone_sse_streams(session_manager) -> int:
    """Close held GET SSE streams without terminating their MCP transports."""
    if session_manager is None or not _streamable_http_drain_enabled():
        return 0
    sessions = getattr(session_manager, "_server_instances", None)
    if not isinstance(sessions, dict):
        RUNTIME_LOGGER.error(
            "Streamable HTTP drain is unavailable",
            extra={"event_name": "streamable_http_drain_unsupported"},
        )
        return 0

    session_count = 0
    for transport in tuple(sessions.values()):
        close_stream = getattr(transport, "close_standalone_sse_stream", None)
        if not callable(close_stream):
            RUNTIME_LOGGER.error(
                "Streamable HTTP drain is unavailable",
                extra={"event_name": "streamable_http_drain_unsupported"},
            )
            continue
        try:
            close_stream()
            session_count += 1
        except Exception:
            RUNTIME_LOGGER.warning(
                "Streamable HTTP session drain error",
                extra={"event_name": "streamable_http_drain_error"},
                exc_info=True,
            )
    RUNTIME_LOGGER.info(
        "Streamable HTTP session drain finished",
        extra={"event_name": "streamable_http_drain_finished", "session_count": session_count},
    )
    return session_count


class _DrainingUvicornServer(uvicorn.Server):
    def __init__(self, config, *, session_manager=None, streamable_http_app=None, path: str | None = None) -> None:
        super().__init__(config)
        self._streamable_session_manager = session_manager
        self._streamable_http_app = streamable_http_app
        self._streamable_http_path = path

    def handle_exit(self, sig, frame) -> None:
        begin_draining()
        RUNTIME_LOGGER.info("Shutdown drain started", extra={"event_name": "shutdown_drain_started", "signal": sig})
        super().handle_exit(sig, frame)

    async def shutdown(self, sockets=None) -> None:
        session_manager = self._streamable_session_manager
        if self._streamable_http_app is not None and self._streamable_http_path is not None:
            session_manager = _get_streamable_session_manager(
                self._streamable_http_app,
                path=self._streamable_http_path,
            )
        _close_standalone_sse_streams(session_manager)
        await asyncio.sleep(0)
        await super().shutdown(sockets=sockets)


def _run_http_server(*, transport: str, host: str, port: int, path: str) -> None:
    """Run the FastMCP HTTP app while preserving FastMCP's Uvicorn defaults."""
    app = mcp.http_app(path=path, transport=transport)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        lifespan="on",
        timeout_graceful_shutdown=20,
        ws="websockets-sansio",
        log_level=os.environ.get("FASTMCP_LOG_LEVEL", "INFO").lower(),
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS"),
    )
    asyncio.run(
        _DrainingUvicornServer(
            config,
            streamable_http_app=app if transport == "streamable-http" else None,
            path=path if transport == "streamable-http" else None,
        ).serve()
    )


configure_logging()
_run_startup_step("configure_error_tracking", configure_error_tracking)

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments. "
        "Call report_problem when a tool error is unclear or even when the tool call succeeded "
        "but the result does not let you answer the user well: "
        "empty result but relevant records were expected; response is missing fields needed to answer; "
        "tool description/docs promised or implied a capability that the result does not provide; "
        "missing tool, parameter, filter, sort, pagination, or date semantics blocks a reasonable request; "
        "workaround was necessary because no direct tool or parameter exists; "
        "successful response is suspicious, inconsistent, or not enough to answer. "
        "Do not call report_problem for legitimately empty results, expected pagination endings, "
        "correct rejections of invalid user input, or normal multi-step composition. "
        "Do not paste raw tool response bodies, raw record IDs, user's verbatim message, "
        "or full error payloads. Describe the shape of the problem, not raw clinic data. "
        "Replace names, patients, phones, and addresses with <client>, <owner>, <patient>, "
        "<phone>, and <address>."
    ),
    lifespan=_runtime_lifespan,
)
mcp.add_middleware(OAuthChallengeMiddleware())
# Must remain after OAuth middleware: its call_next executes inside the
# request-local RuntimeCredentials context, which supplies account_id safely.
mcp.add_middleware(ToolErrorTrackingMiddleware())

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
register_web_routes(mcp)
enhance_tool_descriptions(mcp)
apply_tool_oauth_security_metadata(mcp)

if __name__ == "__main__":
    from secret_manager import SecretManagerError, validate_required_secrets

    try:
        _run_startup_step("validate_required_secrets", validate_required_secrets)
    except SecretManagerError as exc:
        raise SystemExit(1) from exc
    _run_startup_step(
        "validate_feedback_runtime_config",
        lambda: validate_feedback_runtime_config(database_url=get_database_url()),
    )
    transport, host, port, path = _run_startup_step(
        "transport_config",
        _load_runtime_config,
    )
    if transport not in {"http", "streamable-http", "sse"}:
        mcp.run(transport=transport, host=host, port=port, path=path)
    else:
        _run_startup_step(
            "mcp_run",
            lambda: _run_http_server(transport=transport, host=host, port=port, path=path),
        )
