"""Account routes: dashboard, integration, tokens."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from exceptions import AuthError, HostResolutionError, VetmanagerError
from observability_logging import RUNTIME_LOGGER
from secret_manager import get_storage_encryption_key
from service_metrics import record_business_event
from service_token_service import issue_service_bearer_token, revoke_service_bearer_token
from storage import get_session_factory
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY, VETMANAGER_AUTH_MODE_USER_TOKEN
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_ACTIVE,
    save_domain_api_key_connection,
    save_user_login_password_connection,
)
from web_auth import clear_account_session_cookie
from web_security import CSRF_FIELD_NAME, validate_csrf_request


def register_account_routes(
    mcp,
    *,
    observed_route,
    redirect_response,
    read_form,
    get_account_id_from_request,
    render_account_dashboard_response,
    load_account_dashboard,
):
    @observed_route(mcp, "/account", methods=["GET"], include_in_schema=False)
    async def account_page(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = get_account_id_from_request(request)
        if account_id is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response
        return await render_account_dashboard_response(request, account_id)

    @observed_route(mcp, "/account/integration", methods=["POST"], include_in_schema=False)
    async def account_integration_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = get_account_id_from_request(request)
        if account_id is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                integration_error=str(exc),
            )
        auth_mode = form.get("auth_mode", VETMANAGER_AUTH_MODE_DOMAIN_API_KEY).strip()
        domain = form.get("domain", "")
        vm_login = form.get("vm_login", "")
        vm_password = form.get("vm_password", "")

        try:
            async with get_session_factory()() as session:
                if auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
                    await save_user_login_password_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        login=vm_login,
                        password=vm_password,
                        encryption_key=get_storage_encryption_key(),
                    )
                else:
                    await save_domain_api_key_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        api_key=form.get("api_key", ""),
                        encryption_key=get_storage_encryption_key(),
                    )
        except (ValueError, AuthError, HostResolutionError, VetmanagerError) as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=str(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        return await render_account_dashboard_response(
            request,
            account_id,
            integration_success="Vetmanager integration saved successfully.",
        )

    @observed_route(mcp, "/account/integration/reauth", methods=["POST"], include_in_schema=False)
    async def account_integration_reauth_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = get_account_id_from_request(request)
        if account_id is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                integration_error=str(exc),
            )
        auth_mode = form.get("auth_mode", VETMANAGER_AUTH_MODE_DOMAIN_API_KEY).strip()
        domain = form.get("domain", "")
        vm_login = form.get("vm_login", "")
        vm_password = form.get("vm_password", "")

        try:
            async with get_session_factory()() as session:
                if auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
                    await save_user_login_password_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        login=vm_login,
                        password=vm_password,
                        encryption_key=get_storage_encryption_key(),
                    )
                else:
                    await save_domain_api_key_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        api_key=form.get("api_key", ""),
                        encryption_key=get_storage_encryption_key(),
                    )
        except (ValueError, AuthError, HostResolutionError, VetmanagerError) as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=str(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        return await render_account_dashboard_response(
            request,
            account_id,
            integration_success="Vetmanager integration re-authorized successfully.",
        )

    @observed_route(mcp, "/account/tokens", methods=["POST"], include_in_schema=False)
    async def account_token_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = get_account_id_from_request(request)
        if account_id is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                token_error=str(exc),
            )
        (
            account,
            _active_connection_count,
            _bearer_token_count,
            active_connection,
            integration_health_status,
            integration_health_reason,
            _bearer_tokens,
        ) = await load_account_dashboard(account_id)
        if account is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        token_name = form.get("token_name", "")
        expiry_raw = form.get("expires_in_days", "").strip()
        ip_mask_raw = form.get("ip_mask", "*.*.*.*").strip() or "*.*.*.*"

        if active_connection is None or integration_health_status != INTEGRATION_HEALTH_ACTIVE:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=(
                    "Configure Vetmanager integration before issuing bearer tokens."
                    if active_connection is None
                    else integration_health_reason
                ),
                token_name=token_name,
                token_expiry_days=expiry_raw,
                ip_mask=ip_mask_raw,
            )

        try:
            expires_in_days = int(expiry_raw) if expiry_raw else None
            async with get_session_factory()() as session:
                token_row, raw_token = await issue_service_bearer_token(
                    session,
                    account_id=account_id,
                    name=token_name,
                    expires_in_days=expires_in_days,
                    ip_mask=ip_mask_raw,
                )
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=str(exc),
                token_name=token_name,
                token_expiry_days=expiry_raw,
                ip_mask=ip_mask_raw,
            )

        # Stage 107.2 (obs H11): structured business-event log for token issuance
        # so operators can grep when/which account acquired new bearer access.
        RUNTIME_LOGGER.info(
            "Bearer token issued",
            extra={
                "event_name": "bearer_token_issued",
                "account_id": account_id,
                "token_id": getattr(token_row, "id", None),
                "token_name": token_name,
                "expires_in_days": expires_in_days,
            },
        )
        record_business_event("bearer_token_issued")

        return await render_account_dashboard_response(
            request,
            account_id,
            token_success="Bearer token issued successfully.",
            issued_raw_token=raw_token,
        )

    @observed_route(
        mcp,
        "/account/tokens/{token_id:int}/revoke",
        methods=["POST"],
        include_in_schema=False,
    )
    async def account_token_revoke(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = get_account_id_from_request(request)
        if account_id is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                token_error=str(exc),
            )
        token_id = int(request.path_params["token_id"])
        try:
            async with get_session_factory()() as session:
                await revoke_service_bearer_token(
                    session,
                    account_id=account_id,
                    token_id=token_id,
                )
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=str(exc),
            )

        # Stage 107.2 (obs H11): structured log for token revocation.
        RUNTIME_LOGGER.info(
            "Bearer token revoked",
            extra={
                "event_name": "bearer_token_revoked",
                "account_id": account_id,
                "token_id": token_id,
            },
        )
        record_business_event("bearer_token_revoked")

        return await render_account_dashboard_response(
            request,
            account_id,
            token_success="Bearer token revoked successfully.",
        )
