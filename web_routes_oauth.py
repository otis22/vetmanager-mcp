"""OAuth discovery routes for ChatGPT-compatible MCP linking."""

from __future__ import annotations

from fastmcp import FastMCP
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from urllib.parse import quote

from exceptions import RateLimitError
from oauth_metadata import (
    build_authorization_server_metadata,
    build_protected_resource_metadata,
)
from oauth_service import (
    OAUTH_DCR_MAX_BODY_BYTES,
    OAuthRequestError,
    build_authorization_redirect_uri,
    create_oauth_authorization_code,
    exchange_oauth_token,
    narrow_oauth_authorize_request_scope,
    read_oauth_authorize_request,
    register_oauth_client,
    sign_oauth_authorize_request,
    validate_oauth_authorize_request,
)
from storage import get_session_factory
from storage_models import CONNECTION_STATUS_ACTIVE, VetmanagerConnection
from web_html import render_oauth_consent_page
from web_security import (
    CSRF_FIELD_NAME,
    consume_rate_limit,
    get_rate_limit_config,
    get_request_ip,
    validate_csrf_request,
)


def register_oauth_routes(
    mcp: FastMCP,
    *,
    observed_route,
    html_response,
    json_response,
    redirect_response,
    read_form,
    get_account_id_from_request,
    resolve_csrf_token,
) -> None:
    """Register public OAuth discovery routes."""

    @observed_route(
        mcp,
        "/.well-known/oauth-protected-resource",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_protected_resource(request: Request) -> JSONResponse:
        return json_response(request, build_protected_resource_metadata())

    @observed_route(
        mcp,
        "/.well-known/oauth-protected-resource/mcp",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_protected_resource_mcp(request: Request) -> JSONResponse:
        return json_response(request, build_protected_resource_metadata())

    @observed_route(
        mcp,
        "/.well-known/oauth-authorization-server",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_authorization_server(request: Request) -> JSONResponse:
        return json_response(request, build_authorization_server_metadata())

    @observed_route(
        mcp,
        "/.well-known/openid-configuration",
        methods=["GET"],
        include_in_schema=False,
    )
    async def openid_configuration(request: Request) -> JSONResponse:
        return json_response(request, build_authorization_server_metadata())

    @observed_route(
        mcp,
        "/oauth/register",
        methods=["POST"],
        include_in_schema=False,
    )
    async def oauth_register(request: Request) -> JSONResponse:
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return json_response(
                request,
                {
                    "error": "invalid_request",
                    "error_description": "Content-Type must be application/json.",
                },
                status_code=415,
            )

        body = await request.body()
        if len(body) > OAUTH_DCR_MAX_BODY_BYTES:
            return json_response(
                request,
                {
                    "error": "invalid_request",
                    "error_description": "JSON body is too large.",
                },
                status_code=413,
            )

        limit, window_seconds = get_rate_limit_config(
            "OAUTH_DCR_RATE_LIMIT",
            default_attempts=30,
            default_window_seconds=60,
        )
        try:
            await consume_rate_limit(
                "oauth_dcr",
                get_request_ip(request),
                limit=limit,
                window_seconds=window_seconds,
            )
        except RateLimitError:
            return json_response(
                request,
                {
                    "error": "temporarily_unavailable",
                    "error_description": "Too many registration attempts.",
                },
                status_code=429,
            )

        try:
            payload = await request.json()
        except Exception:
            return json_response(
                request,
                {
                    "error": "invalid_request",
                    "error_description": "Malformed JSON body.",
                },
                status_code=400,
            )

        try:
            async with get_session_factory()() as session:
                response_payload = await register_oauth_client(session, payload)
        except OAuthRequestError as exc:
            return json_response(
                request,
                {
                    "error": exc.error,
                    "error_description": exc.description,
                },
                status_code=exc.status_code,
            )

        return json_response(request, response_payload, status_code=201)

    @observed_route(
        mcp,
        "/oauth/authorize",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_authorize(request: Request) -> HTMLResponse | RedirectResponse | JSONResponse:
        try:
            async with get_session_factory()() as session:
                request_data = await validate_oauth_authorize_request(session, request.query_params)
        except OAuthRequestError as exc:
            return json_response(
                request,
                {
                    "error": exc.error,
                    "error_description": exc.description,
                },
                status_code=exc.status_code,
            )

        account_id = get_account_id_from_request(request)
        if account_id is None:
            next_url = request.url.path
            if request.url.query:
                next_url = f"{next_url}?{request.url.query}"
            return redirect_response(request, url=f"/login?next={quote(next_url, safe='')}", status_code=303)

        async with get_session_factory()() as session:
            connections = (
                await session.execute(
                    select(VetmanagerConnection)
                    .where(
                        VetmanagerConnection.account_id == account_id,
                        VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
                    )
                    .order_by(VetmanagerConnection.id.asc())
                )
            ).scalars().all()
        if not connections:
            return html_response(
                request,
                render_oauth_consent_page(
                    csrf_token=resolve_csrf_token(request),
                    request_state="",
                    client_name=request_data["client_name"],
                    scopes=request_data["scopes"],
                    connections=[],
                    error="No active Vetmanager connection is available for this account.",
                ),
                status_code=400,
                with_csrf_cookie=True,
                csrf_token=resolve_csrf_token(request),
                no_store=True,
            )

        csrf_token = resolve_csrf_token(request)
        return html_response(
            request,
            render_oauth_consent_page(
                csrf_token=csrf_token,
                request_state=sign_oauth_authorize_request(request_data),
                client_name=request_data["client_name"],
                scopes=request_data["scopes"],
                connections=[
                    {"id": connection.id, "domain": connection.domain or "n/a"}
                    for connection in connections
                ],
            ),
            with_csrf_cookie=True,
            csrf_token=csrf_token,
            no_store=True,
        )

    @observed_route(
        mcp,
        "/oauth/authorize/consent",
        methods=["POST"],
        include_in_schema=False,
    )
    async def oauth_authorize_consent(request: Request) -> HTMLResponse | RedirectResponse:
        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
            request_data = read_oauth_authorize_request(form.get("request_state", ""))
            connection_id = int(form.get("connection_id", ""))
            request_data = narrow_oauth_authorize_request_scope(
                request_data,
                access_preset=form.get("access_preset", ""),
                confirm_full_access=form.get("confirm_full_access") == "1",
            )
        except (OAuthRequestError, ValueError) as exc:
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_oauth_consent_page(
                    csrf_token=csrf_token,
                    request_state=form.get("request_state", ""),
                    client_name="ChatGPT",
                    scopes=[],
                    connections=[],
                    error=str(exc),
                ),
                status_code=400,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
                no_store=True,
            )

        account_id = get_account_id_from_request(request)
        if account_id is None:
            return redirect_response(request, url="/login", status_code=303)

        async with get_session_factory()() as session:
            connection = await session.scalar(
                select(VetmanagerConnection).where(
                    VetmanagerConnection.id == connection_id,
                    VetmanagerConnection.account_id == account_id,
                    VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
                )
            )
            if connection is None:
                csrf_token = resolve_csrf_token(request)
                return html_response(
                    request,
                    render_oauth_consent_page(
                        csrf_token=csrf_token,
                        request_state=form.get("request_state", ""),
                        client_name=str(request_data.get("client_name") or "ChatGPT"),
                        scopes=list(request_data.get("scopes") or []),
                        connections=[],
                        error="Selected Vetmanager connection is not active.",
                    ),
                    status_code=400,
                    with_csrf_cookie=True,
                    csrf_token=csrf_token,
                    no_store=True,
                )
            raw_code = await create_oauth_authorization_code(
                session,
                request_data,
                account_id=account_id,
                vetmanager_connection_id=connection.id,
            )

        return redirect_response(
            request,
            url=build_authorization_redirect_uri(
                request_data["redirect_uri"],
                code=raw_code,
                state=str(request_data.get("state") or ""),
            ),
            status_code=303,
        )

    @observed_route(
        mcp,
        "/oauth/token",
        methods=["POST"],
        include_in_schema=False,
    )
    async def oauth_token(request: Request) -> JSONResponse:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            return json_response(
                request,
                {
                    "error": "invalid_request",
                    "error_description": "Content-Type must be application/x-www-form-urlencoded.",
                },
                status_code=415,
            )

        form = await read_form(request)
        limit, window_seconds = get_rate_limit_config(
            "OAUTH_TOKEN_RATE_LIMIT",
            default_attempts=60,
            default_window_seconds=60,
        )
        try:
            await consume_rate_limit(
                "oauth_token",
                get_request_ip(request),
                limit=limit,
                window_seconds=window_seconds,
            )
        except RateLimitError:
            return json_response(
                request,
                {
                    "error": "temporarily_unavailable",
                    "error_description": "Too many token requests.",
                },
                status_code=429,
            )

        try:
            async with get_session_factory()() as session:
                payload = await exchange_oauth_token(session, form)
        except OAuthRequestError as exc:
            return json_response(
                request,
                {
                    "error": exc.error,
                    "error_description": exc.description,
                },
                status_code=exc.status_code,
            )
        return json_response(request, payload)
