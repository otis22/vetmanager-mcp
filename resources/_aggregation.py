"""Shared partial-gather helper for aggregator resources (stage 103.7 / 106.3).

Pattern used by `resources.client_profile` and `resources.pet_profile`:
- Fire N parallel sub-requests via `asyncio.gather(return_exceptions=True)`.
- Re-raise `asyncio.CancelledError` explicitly (it's BaseException, not
  Exception — catching it as a section would break cooperative cancel).
- Collect other `Exception` instances into a `section_errors` dict.
- Surface an `"aggregator_partial"` structured log when degraded.

Stage 106.3 (F5): moved from `tools/_aggregation.py` to the resources/ layer
to eliminate the resources → tools upward import. `tools/_aggregation.py`
remains as a BC shim re-exporting this function.

Usage:
    from resources._aggregation import gather_sections

    (client_payload, invoices_payload, ...), section_errors = \\
        await gather_sections(
            tool_name="get_client_profile",
            context={"client_id": client_id},
            sections=[
                ("client",   vc.get(...), {"data": {"client": {}}}),
                ("invoices", vc.get(...), {"data": {"invoice": []}}),
                ...
            ],
        )
"""

from __future__ import annotations

import asyncio
from typing import Any


async def gather_sections(
    *,
    tool_name: str,
    context: dict,
    sections: list[tuple[str, Any, dict]],
) -> tuple[list[dict], dict[str, str]]:
    """Fire `sections` in parallel; return (payloads, section_errors).

    Args:
        tool_name: Used in "aggregator_partial" warning log event.
        context: Extra fields for the warning log (e.g. {"client_id": 7}).
        sections: List of (section_name, coro, fallback_shape) triples.
            Coroutines are awaited in parallel. On per-section Exception
            the fallback_shape is substituted and the error stored in
            `section_errors[section_name]`. CancelledError re-raises.

    Returns:
        (payloads, section_errors) where payloads is a list aligned with
        input `sections` order.
    """
    coros = [coro for _, coro, _ in sections]
    results = await asyncio.gather(*coros, return_exceptions=True)

    # Cooperative cancellation must propagate — never swallow CancelledError.
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            raise r

    # Stage 102.7: structured section_errors shape for programmatic
    # consumption by LLM clients:
    #   {section_name: {"error_type": str, "retryable": bool, "message": str}}
    # Free-text flat string form is kept as `.str` rendering for log field.
    from exceptions import (
        AuthError, HostResolutionError, NotFoundError,
        RateLimitError, VetmanagerError, VetmanagerTimeoutError,
        VetmanagerUpstreamUnavailable,
    )

    def _classify(exc: Exception) -> tuple[str, bool]:
        if isinstance(exc, VetmanagerUpstreamUnavailable):
            return ("upstream_unavailable", True)
        if isinstance(exc, VetmanagerTimeoutError):
            return ("timeout", True)
        if isinstance(exc, RateLimitError):
            return ("rate_limit", True)
        if isinstance(exc, HostResolutionError):
            return ("host_resolution", True)
        if isinstance(exc, AuthError):
            return ("auth", False)
        if isinstance(exc, NotFoundError):
            return ("not_found", False)
        if isinstance(exc, VetmanagerError):
            # Generic VM error (incl. 5xx wrap) — usually retryable.
            return ("vetmanager_error", True)
        return ("unexpected", False)

    # Stage 107.5 (F9 fix): AuthError messages may embed a masked API key
    # fragment (e.g. `"Invalid or missing API key (ab***yz)"`). Logging
    # that fragment to section_errors[name].message ships it to the log
    # aggregator. Scrub AuthError to exception-class-name only; other
    # exception types log their full message (useful operational context).
    from exceptions import AuthError

    section_errors: dict[str, dict] = {}
    payloads: list[dict] = []
    for (name, _, fallback), result in zip(sections, results):
        if isinstance(result, Exception):
            error_type, retryable = _classify(result)
            message = (
                type(result).__name__
                if isinstance(result, AuthError)
                else f"{type(result).__name__}: {result}"
            )
            section_errors[name] = {
                "error_type": error_type,
                "retryable": retryable,
                "message": message,
            }
            payloads.append(fallback)
        else:
            payloads.append(result)

    if section_errors:
        from observability_logging import RUNTIME_LOGGER
        from request_context import get_current_request_context
        # Stage 107.4 (obs F4 fix): propagate correlation_id / request_id
        # into the aggregator_partial log so SREs can join it with the
        # upstream vm_upstream_timeout / vm_upstream_network_error events
        # from the same request chain.
        _ctx = get_current_request_context() or {}
        RUNTIME_LOGGER.warning(
            f"{tool_name} partial failure",
            extra={
                "event_name": "aggregator_partial",
                "tool": tool_name,
                "section_errors": section_errors,
                **_ctx,
                **context,
            },
        )

    return payloads, section_errors
