"""Shared partial-gather helper for aggregator tools (stage 103.7).

Pattern used by `get_client_profile` and `get_pet_profile`:
- Fire N parallel sub-requests via `asyncio.gather(return_exceptions=True)`.
- Re-raise `asyncio.CancelledError` explicitly (it's BaseException, not
  Exception — catching it as a section would break cooperative cancel).
- Collect other `Exception` instances into a `section_errors` dict.
- Surface an `"aggregator_partial"` structured log when degraded.

Usage:
    from tools._aggregation import gather_sections

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

    section_errors: dict[str, dict] = {}
    payloads: list[dict] = []
    for (name, _, fallback), result in zip(sections, results):
        if isinstance(result, Exception):
            error_type, retryable = _classify(result)
            section_errors[name] = {
                "error_type": error_type,
                "retryable": retryable,
                "message": f"{type(result).__name__}: {result}",
            }
            payloads.append(fallback)
        else:
            payloads.append(result)

    if section_errors:
        from observability_logging import RUNTIME_LOGGER
        RUNTIME_LOGGER.warning(
            f"{tool_name} partial failure",
            extra={
                "event_name": "aggregator_partial",
                "tool": tool_name,
                "section_errors": section_errors,
                **context,
            },
        )

    return payloads, section_errors
