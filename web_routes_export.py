"""The public route that hands out one cleaned report export.

Stage 276. There is no authorization header here and there cannot be: the
whole point of the link is that a person can open it in a browser. So the
route checks what it can — that the path is one this server could have signed,
that the file is younger than three days, and that the access it was issued to
is still alive — and answers every refusal identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

import report_export
from observability_logging import RUNTIME_LOGGER
from privacy_utils import REPORT_EXPORT_ROUTE_TEMPLATE
from request_context import attach_request_context_headers, get_request_context
from service_metrics import record_report_export_serve
from storage import get_session_factory
from storage_models import (
    OAUTH_STATUS_ACTIVE,
    OAuthAccessToken,
    OAuthGrant,
    ServiceBearerToken,
)


SUBJECT_BEARER = "service_bearer"
SUBJECT_OAUTH = "oauth_access_token"
ACCESS_CHECK_TIMEOUT_SECONDS = 2.0
NOT_FOUND_BODY = "not found\n"


async def _subject_is_alive(subject_type: str, subject_id: int) -> bool:
    """Is the access this file was issued to still live?

    Deliberately narrow: this asks whether the token or grant still exists and
    is active, not what it is allowed to do now. The file was already cleaned
    under the rules in force when it was made, and re-deciding rights on an
    unauthenticated route would be a second, weaker copy of the access model.
    """
    factory = get_session_factory()
    async with factory() as session:
        if subject_type == SUBJECT_BEARER:
            token = await session.get(ServiceBearerToken, subject_id)
            return token is not None and token.is_active(now=datetime.now(timezone.utc))
        if subject_type == SUBJECT_OAUTH:
            grant_status = await session.scalar(
                select(OAuthGrant.status)
                .join(OAuthAccessToken, OAuthAccessToken.grant_id == OAuthGrant.id)
                .where(OAuthAccessToken.id == subject_id)
            )
            return grant_status == OAUTH_STATUS_ACTIVE
    return False


def register_export_routes(mcp, *, observed_route, plain_text_response) -> None:
    """Register the report export download route."""

    @observed_route(
        mcp,
        REPORT_EXPORT_ROUTE_TEMPLATE,
        methods=["GET"],
        include_in_schema=False,
    )
    async def report_export_download(request: Request) -> Response:
        def _not_found(outcome: str) -> Response:
            record_report_export_serve(outcome=outcome)
            return plain_text_response(request, NOT_FOUND_BODY, status_code=404)

        owner = request.path_params.get("owner") or ""
        name = request.path_params.get("name") or ""
        if name.endswith(".csv"):
            name = name[: -len(".csv")]

        stored = report_export.resolve_export(owner, name)
        if stored is None:
            return _not_found("not_found")

        # Only now, with a path that matched a real file, is the database
        # touched: an unauthenticated route must not be a way to make queries.
        try:
            alive = await asyncio.wait_for(
                _subject_is_alive(stored.subject_type, stored.subject_id),
                timeout=ACCESS_CHECK_TIMEOUT_SECONDS,
            )
            refusal = "revoked"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A broken check is not a revoked token, and the counter must not
            # say it was: the answer is the same 404, the reason is not.
            RUNTIME_LOGGER.warning(
                "Report export access check failed.",
                extra={
                    "event_name": "report_export_access_check_failed",
                    "route": REPORT_EXPORT_ROUTE_TEMPLATE,
                    "error_class": exc.__class__.__name__,
                    **get_request_context(request),
                },
            )
            alive, refusal = False, "access_check_failed"
        if not alive:
            return _not_found(refusal)

        try:
            body = await asyncio.to_thread(stored.path.read_bytes)
        except OSError:
            return _not_found("not_found")

        record_report_export_serve(outcome="served")
        response = Response(
            content=body,
            media_type=report_export.REPORT_EXPORT_CONTENT_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{stored.download_name}"',
                "X-Content-Type-Options": "nosniff",
                "X-Robots-Tag": "noindex, nofollow",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )
        attach_request_context_headers(response, request)
        return response
