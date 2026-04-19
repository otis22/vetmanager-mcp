import atexit
import logging
import os
import asyncio
import signal

from fastmcp import FastMCP

from error_tracking import configure_error_tracking
from storage import bootstrap_storage_schema, get_database_url, initialize_storage
from structured_logging import configure_logging
from tool_descriptions import enhance_tool_descriptions
from vetmanager_client import reset_breakers, reset_shared_http_client
from web import register_web_routes

configure_logging()
configure_error_tracking()

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments."
    ),
)

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
register_web_routes(mcp)
enhance_tool_descriptions(mcp)

async def _graceful_shutdown() -> None:
    """Stage 99.3: close shared httpx.AsyncClient keep-alive sockets with
    FIN instead of RST on SIGTERM / process exit. Also drop breaker state
    so a future in-process restart starts clean.

    Stage 107.8 (obs): structured logs via RUNTIME_LOGGER with event_name
    so operators can grep shutdown paths; the `reset_breakers` branch
    was previously silent on failure.
    """
    from observability_logging import RUNTIME_LOGGER
    from host_resolver import reset_billing_resolver
    try:
        await reset_shared_http_client()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_shared_http_client"},
            exc_info=True,
        )
    try:
        await reset_breakers()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_breakers"},
            exc_info=True,
        )
    # Stage 113.F7: close billing-api resolver client + drop TTL cache.
    try:
        await reset_billing_resolver()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_billing_resolver"},
            exc_info=True,
        )


def _install_shutdown_handlers() -> None:
    """Register SIGTERM/SIGINT handlers that drain the http pool cleanly.

    FastMCP's internal uvicorn runner already handles SIGINT — we wrap it
    only to guarantee shared-client cleanup. Uses `atexit` as a final
    backstop for unusual exit paths (test runners, embedded use).
    """

    def _run_once() -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_graceful_shutdown())
            else:
                loop.run_until_complete(_graceful_shutdown())
        except Exception:
            pass

    atexit.register(_run_once)
    # SIGTERM (docker stop) and SIGINT (Ctrl+C).
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: _run_once())
    except (ValueError, OSError):
        # Not main thread or unsupported platform — atexit is sufficient.
        pass


if __name__ == "__main__":
    from secret_manager import SecretManagerError, validate_required_secrets

    try:
        validate_required_secrets()
    except SecretManagerError as exc:
        logging.critical("Startup aborted: %s", exc)
        raise SystemExit(1) from exc
    asyncio.run(initialize_storage())
    if get_database_url().startswith("sqlite"):
        asyncio.run(bootstrap_storage_schema())
    _install_shutdown_handlers()
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp")
    mcp.run(transport=transport, host=host, port=port, path=path)
