"""Account routes: dashboard, integration, tokens."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from activation_events import (
    classify_activation_device,
    classify_activation_reason,
    record_activation_event_best_effort,
)
from exceptions import (
    AuthError,
    HostResolutionError,
    VetmanagerError,
    VetmanagerTimeoutError,
    VetmanagerUpstreamUnavailable,
)
from observability_logging import RUNTIME_LOGGER
from secret_manager import get_storage_encryption_key
from service_metrics import record_auth_failure, record_business_event, record_token_preset_issued
from service_token_service import issue_service_bearer_token, revoke_service_bearer_token
from oauth_service import revoke_oauth_grant_family
from tool_access_registry import PRESET_FULL_ACCESS, PRESET_REPORT_AI, get_token_preset_label
from storage import get_session_factory
from storage_models import (
    CONNECTION_STATUS_ACTIVE,
    TOKEN_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TokenUsageStat,
    VetmanagerConnection,
)
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY, VETMANAGER_AUTH_MODE_USER_TOKEN
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_ACTIVE,
    save_domain_api_key_connection,
    save_user_login_password_connection,
)
from web_auth import clear_account_session_cookie
from web_html import _DOCTOR_PRESET_FORM_VALUE, QUICK_TOKEN_NAME
from web_security import CSRF_FIELD_NAME, get_request_ip, validate_csrf_request


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")

# Stage 196.3: user-facing Russian texts with a concrete next step. Exception
# messages themselves stay English — they feed logs, metrics, and the MCP layer.
INTEGRATION_SAVED_MESSAGE = (
    "Интеграция Vetmanager сохранена. Следующий шаг — выпустите Bearer token."
)
INTEGRATION_REAUTH_MESSAGE = "Повторная авторизация выполнена, user token обновлён."


def _integration_error_text(exc: Exception) -> str:
    """Map an integration save failure to a Russian message with a next step."""
    message = str(exc)
    if "domain format" in message:
        return (
            "Неверный формат домена клиники. Укажите только поддомен из адреса, "
            "по которому вы открываете Vetmanager: для myclinic.vetmanager.ru "
            "это myclinic."
        )
    if "Invalid Vetmanager API key" in message:
        return (
            "Vetmanager не принял API key. Проверьте, что ключ скопирован целиком: "
            "в Vetmanager откройте Настройки → Интеграция с сервисами → REST API "
            "и скопируйте API KEY заново."
        )
    if "Invalid Vetmanager login or password" in message:
        return (
            "Vetmanager не принял логин или пароль. Проверьте данные, с которыми "
            "вы входите в Vetmanager, и попробуйте ещё раз."
        )
    if isinstance(exc, (VetmanagerTimeoutError, VetmanagerUpstreamUnavailable)) or (
        "timed out" in message or "unavailable" in message
    ):
        return (
            "Vetmanager сейчас не отвечает. Подождите минуту и попробуйте ещё раз — "
            "данные формы сохранены."
        )
    if isinstance(exc, HostResolutionError):
        return (
            "Не нашли клинику с таким доменом. Проверьте поддомен из адреса, "
            "по которому вы открываете Vetmanager (для myclinic.vetmanager.ru "
            "это myclinic)."
        )
    return message


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase exception class name to snake_case metric label.

    Stage 112.2: `AuthError` → `auth_error`, `HostResolutionError` →
    `host_resolution_error`, `ValueError` → `value_error`. Produces
    human-queryable Prometheus label values.
    """
    return _CAMEL_BOUNDARY.sub("_", name).lower()


async def _record_activation_event_for_account(
    *,
    account_id: int,
    event_name: str,
    auth_mode: str | None = None,
    device_class: str | None = None,
    reason_class: str | None = None,
    copy_kind: str | None = None,
) -> None:
    """Record activation telemetry without affecting the account route result."""
    try:
        async with get_session_factory()() as session:
            await record_activation_event_best_effort(
                session,
                account_id=account_id,
                event_name=event_name,
                auth_mode=auth_mode,
                device_class=device_class,
                reason_class=reason_class,
                copy_kind=copy_kind,
            )
    except Exception as exc:  # pragma: no cover - defensive route boundary
        RUNTIME_LOGGER.warning(
            "Activation event route recording failed",
            extra={
                "event_name": "activation_event_route_record_failed",
                "account_id": account_id,
                "activation_event": event_name,
                "error_class": type(exc).__name__,
            },
        )


async def _load_activation_state_for_polling(account_id: int) -> str | None:
    """Return activation state for polling without probing Vetmanager upstream.

    The account page already evaluated connection health before rendering the
    waiting state. Polling only needs to detect whether a token has received its
    first MCP request, so this must stay DB-only and cheap.
    """
    async with get_session_factory()() as session:
        account = await session.get(Account, account_id)
        if account is None or account.archived_at is not None or account.status != "active":
            return None
        active_connection = await session.scalar(
            select(VetmanagerConnection.id)
            .where(VetmanagerConnection.account_id == account_id)
            .where(VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE)
            .limit(1)
        )
        if active_connection is None:
            return "needs_connection"

        usable_token_ids = [
            int(token_id)
            for token_id in (
                await session.execute(
                    select(ServiceBearerToken.id)
                    .where(ServiceBearerToken.account_id == account_id)
                    .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
                    .where(
                        (ServiceBearerToken.expires_at.is_(None))
                        | (ServiceBearerToken.expires_at > func.now())
                    )
                )
            ).scalars().all()
        ]
        if not usable_token_ids:
            return "needs_token"

        used_token = await session.scalar(
            select(ServiceBearerToken.id)
            .outerjoin(
                TokenUsageStat,
                TokenUsageStat.bearer_token_id == ServiceBearerToken.id,
            )
            .where(ServiceBearerToken.id.in_(usable_token_ids))
            .where(
                (ServiceBearerToken.last_used_at.is_not(None))
                | (TokenUsageStat.last_used_at.is_not(None))
                | (TokenUsageStat.request_count > 0)
            )
            .limit(1)
        )
        if used_token is None:
            return "needs_client_use"
        return "ready"


def register_account_routes(
    mcp,
    *,
    observed_route,
    redirect_response,
    read_form,
    get_account_id_from_request,
    render_account_dashboard_response,
    load_account_dashboard,
    json_response,
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
        auth_mode = form.get("auth_mode", VETMANAGER_AUTH_MODE_DOMAIN_API_KEY).strip()
        device_class = classify_activation_device(request.headers)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                integration_error=str(exc),
            )
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
            if not isinstance(exc, (VetmanagerTimeoutError, VetmanagerUpstreamUnavailable)):
                await _record_activation_event_for_account(
                    account_id=account_id,
                    event_name="integration_failed",
                    auth_mode=auth_mode,
                    device_class=device_class,
                    reason_class=classify_activation_reason(exc),
                )
            # Stage 112.2 (super-review 2026-04-19): structured log + metric
            # so support can find the event by account_id and SRE can alert
            # on integration_save_failed spikes. Do NOT include str(exc) —
            # AuthError.message may embed masked API-key fragments.
            RUNTIME_LOGGER.warning(
                "Integration save failed",
                extra={
                    "event_name": "integration_save_failed",
                    "account_id": account_id,
                    "auth_mode": auth_mode,
                    "error_class": exc.__class__.__name__,
                },
            )
            record_auth_failure(
                source="web_integration",
                reason=_camel_to_snake(exc.__class__.__name__),
            )
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=_integration_error_text(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        await _record_activation_event_for_account(
            account_id=account_id,
            event_name="integration_saved",
            auth_mode=auth_mode,
            device_class=device_class,
        )
        return await render_account_dashboard_response(
            request,
            account_id,
            integration_success=INTEGRATION_SAVED_MESSAGE,
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
            # Stage 112.2: same pattern as account_integration_submit above.
            RUNTIME_LOGGER.warning(
                "Integration reauth failed",
                extra={
                    "event_name": "integration_save_failed",
                    "account_id": account_id,
                    "auth_mode": auth_mode,
                    "error_class": exc.__class__.__name__,
                    "flow": "reauth",
                },
            )
            record_auth_failure(
                source="web_integration_reauth",
                reason=_camel_to_snake(exc.__class__.__name__),
            )
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=_integration_error_text(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        return await render_account_dashboard_response(
            request,
            account_id,
            integration_success=INTEGRATION_REAUTH_MESSAGE,
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
            _oauth_grants,
        ) = await load_account_dashboard(account_id)
        if account is None:
            response = redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        token_name = form.get("token_name", "")
        expiry_raw = form.get("expires_in_days", "").strip()
        request_ip = get_request_ip(request)
        ip_mask_raw = form.get("ip_mask", "").strip()
        access_preset = form.get("access_preset", PRESET_REPORT_AI)
        if access_preset == _DOCTOR_PRESET_FORM_VALUE:
            access_preset = "doctor"
        is_depersonalized = form.get("is_depersonalized") == "1"
        confirm_full_access = form.get("confirm_full_access") == "1"
        confirm_wildcard_ip = form.get("confirm_wildcard_ip") == "1"
        # Stage 197.2: one-click issuance. The quick form carries an explicit
        # IP-scope radio; choosing "any" IS the wildcard confirmation (the
        # stage-155 explicit-ip_mask service contract stays intact — the
        # wildcard warning log still fires in issue_service_bearer_token).
        quick_ip_choice = form.get("quick_ip_choice", "").strip()
        if quick_ip_choice:
            if not token_name.strip():
                token_name = QUICK_TOKEN_NAME
            if quick_ip_choice == "any":
                ip_mask_raw = "*.*.*.*"
                confirm_wildcard_ip = True
            else:
                ip_mask_raw = "" if request_ip == "unknown" else request_ip
        if not ip_mask_raw:
            if request_ip == "unknown":
                ip_mask_raw = ""
            else:
                ip_mask_raw = request_ip

        if active_connection is None or integration_health_status != INTEGRATION_HEALTH_ACTIVE:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=(
                    "Сначала подключите Vetmanager, затем можно выпускать Bearer-токены."
                    if active_connection is None
                    else integration_health_reason
                ),
                token_name=token_name,
                token_expiry_days=expiry_raw,
                ip_mask=ip_mask_raw,
                token_access_preset=access_preset,
                token_is_depersonalized=is_depersonalized,
            )

        try:
            expires_in_days = int(expiry_raw) if expiry_raw else 30
            if not ip_mask_raw:
                raise ValueError("IP mask is required when request IP is unavailable.")
            if access_preset == PRESET_FULL_ACCESS and not confirm_full_access:
                raise ValueError("Confirm full access before issuing this token.")
            if ip_mask_raw == "*.*.*.*" and not confirm_wildcard_ip:
                raise ValueError("Confirm unrestricted IP access before issuing this token.")
            async with get_session_factory()() as session:
                token_row, raw_token = await issue_service_bearer_token(
                    session,
                    account_id=account_id,
                    name=token_name,
                    expires_in_days=expires_in_days,
                    ip_mask=ip_mask_raw,
                    access_preset=access_preset,
                    is_depersonalized=is_depersonalized,
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
                token_access_preset=access_preset,
                token_is_depersonalized=is_depersonalized,
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
                "access_preset": access_preset,
                "is_depersonalized": is_depersonalized,
            },
        )
        record_business_event("bearer_token_issued")
        record_token_preset_issued(access_preset)

        return await render_account_dashboard_response(
            request,
            account_id,
            token_success="Bearer token выпущен.",
            issued_raw_token=raw_token,
            issued_token_access_label=get_token_preset_label(access_preset),
            issued_token_privacy_label="Depersonalized" if is_depersonalized else "Standard",
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
            token_success="Bearer token отозван.",
        )

    @observed_route(
        mcp,
        "/account/oauth-grants/{grant_id:int}/revoke",
        methods=["POST"],
        include_in_schema=False,
    )
    async def account_oauth_grant_revoke(request: Request) -> HTMLResponse | RedirectResponse:
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

        grant_id = int(request.path_params["grant_id"])
        try:
            async with get_session_factory()() as session:
                revoke_result = await revoke_oauth_grant_family(
                    session,
                    account_id=account_id,
                    grant_id=grant_id,
                )
        except ValueError as exc:
            return await render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=str(exc),
            )

        if revoke_result.grant_transitioned:
            RUNTIME_LOGGER.info(
                "OAuth grant revoked",
                extra={
                    "event_name": "oauth_grant_revoked",
                    "account_id": account_id,
                    "grant_id": grant_id,
                    "grant_transitioned": revoke_result.grant_transitioned,
                    "access_tokens_transitioned": revoke_result.access_tokens_transitioned,
                    "refresh_tokens_transitioned": revoke_result.refresh_tokens_transitioned,
                },
            )
            record_business_event("oauth_grant_revoked")
        elif revoke_result.any_transition:
            RUNTIME_LOGGER.info(
                "OAuth grant family repaired",
                extra={
                    "event_name": "oauth_grant_family_repaired",
                    "account_id": account_id,
                    "grant_id": grant_id,
                    "grant_transitioned": revoke_result.grant_transitioned,
                    "access_tokens_transitioned": revoke_result.access_tokens_transitioned,
                    "refresh_tokens_transitioned": revoke_result.refresh_tokens_transitioned,
                },
            )
        else:
            RUNTIME_LOGGER.info(
                "OAuth grant revoke no-op",
                extra={
                    "event_name": "oauth_grant_revoke_noop",
                    "account_id": account_id,
                    "grant_id": grant_id,
                },
            )

        return await render_account_dashboard_response(
            request,
            account_id,
            token_success="ChatGPT connection отключена.",
        )

    @observed_route(
        mcp,
        "/account/telemetry/token-copied",
        methods=["POST"],
        include_in_schema=False,
    )
    async def account_token_copied(request: Request) -> Response:
        """Stage 197.3: activation telemetry — user copied token/config/MCP URL.

        Fired from the account page copy buttons via fetch. CSRF-protected like
        every other account POST; records only an aggregate business event and
        a structured log without secrets.
        """
        account_id = get_account_id_from_request(request)
        if account_id is None:
            return json_response(request, {"error": "unauthorized"}, status_code=401)

        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError:
            return json_response(request, {"error": "csrf"}, status_code=403)

        kind = form.get("kind", "")
        if kind not in {"token", "config", "mcp_url"}:
            kind = "unknown"
        await _record_activation_event_for_account(
            account_id=account_id,
            event_name="token_copied",
            auth_mode="unknown",
            device_class=classify_activation_device(request.headers),
            copy_kind=kind,
        )
        RUNTIME_LOGGER.info(
            "Token copied",
            extra={
                "event_name": "token_copied",
                "account_id": account_id,
                "copy_kind": kind,
            },
        )
        record_business_event("token_copied")
        return Response(status_code=204)

    @observed_route(
        mcp,
        "/account/activation-status",
        methods=["GET"],
        include_in_schema=False,
    )
    async def account_activation_status(request: Request) -> Response:
        """Stage 197.4: current activation state for the waiting indicator.

        The account page polls this while it waits for the first MCP request
        and reloads once the state changes.
        """
        account_id = get_account_id_from_request(request)
        if account_id is None:
            return json_response(request, {"error": "unauthorized"}, status_code=401)

        state = await _load_activation_state_for_polling(account_id)
        if state is None:
            return json_response(request, {"error": "unauthorized"}, status_code=401)
        return json_response(request, {"state": state})
