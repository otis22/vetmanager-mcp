"""Unit tests for stage 23.2 Vetmanager connection save/validation service."""

import asyncio
from pathlib import Path
import ssl

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import select

from exceptions import (
    AuthError,
    HostResolutionError,
    VetmanagerError,
    VetmanagerTimeoutError,
    VetmanagerTlsError,
)
from storage_models import VetmanagerConnection
from vetmanager_connection_service import (
    _login_prepare_fingerprint,
    exchange_user_token,
    evaluate_connection_health,
    save_domain_api_key_connection,
    save_user_login_password_connection,
    save_user_token_connection,
    validate_domain_api_key_connection,
)
from service_metrics import reset_service_metrics, snapshot_service_metrics


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


def test_login_prepare_fingerprint_does_not_expose_raw_password():
    fingerprint = _login_prepare_fingerprint(
        normalized_domain="clinic-login",
        login="doctor",
        password="doctor-pass-123",
    )

    assert "doctor" not in fingerprint
    assert "doctor-pass-123" not in fingerprint
    assert fingerprint != _login_prepare_fingerprint(
        normalized_domain="clinic-login",
        login="doctor",
        password="other-pass",
    )


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "connection-service.db")


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_persists_validated_active_connection(session_factory):
    """Saving connection should validate host/key and persist encrypted active record."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-a.vetmanager.cloud"}})
    )
    respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        connection = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-a",
            api_key="secret-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.auth_mode == "domain_api_key"
    assert stored.domain == "clinic-a"
    assert stored.encrypted_credentials is not None
    assert "secret-key" not in stored.encrypted_credentials


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_disables_previous_active_connection(session_factory):
    """Account should keep only one active Vetmanager connection after save."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-b").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-b.vetmanager.cloud"}})
    )
    respx.get("https://clinic-b.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        old = VetmanagerConnection(
            account_id=1,
            auth_mode="domain_api_key",
            status="active",
            domain="old-clinic",
        )
        old.set_credentials(
            {"domain": "old-clinic", "api_key": "old-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(old)
        await session.commit()

    async with session_factory() as session:
        new = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-b",
            api_key="new-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(VetmanagerConnection)
                .where(VetmanagerConnection.account_id == 1)
                .order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    assert rows[0].status == "disabled"
    assert rows[1].id == new.id
    assert rows[1].status == "active"


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_rejects_invalid_api_key(session_factory):
    """Connection save should fail safely when API key is invalid."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-c").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-c.vetmanager.cloud"}})
    )
    respx.get("https://clinic-c.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid Vetmanager API key"):
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-c",
                api_key="bad-key",
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
@respx.mock
async def test_save_user_token_connection_persists_encrypted_active_connection(session_factory):
    """User-token mode should validate probe and persist encrypted credentials."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user.vetmanager.cloud"}})
    )
    respx.get("https://clinic-user.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        connection = await save_user_token_connection(
            session,
            account_id=1,
            domain="clinic-user",
            user_token="user-token-secret",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.auth_mode == "user_token"
    assert stored.domain == "clinic-user"
    assert stored.encrypted_credentials is not None
    assert "user-token-secret" not in stored.encrypted_credentials


@pytest.mark.asyncio
@respx.mock
async def test_save_user_token_connection_rejects_invalid_user_token(session_factory):
    """User-token mode should fail safely when runtime token probe is unauthorized."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user-bad").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user-bad.vetmanager.cloud"}})
    )
    respx.get("https://clinic-user-bad.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid Vetmanager user token"):
            await save_user_token_connection(
                session,
                account_id=1,
                domain="clinic-user-bad",
                user_token="bad-user-token",
                app_name="vetmanager-mcp",
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
@respx.mock
async def test_exchange_user_token_uses_multipart_form_and_app_name_without_api_key():
    """Login/password exchange must use multipart form-data with app_name only."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-auth").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-auth.vetmanager.cloud"}})
    )

    captured: dict[str, object] = {}

    def _token_auth_response(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"data": {"token": "fresh-user-token"}})

    respx.post("https://clinic-auth.vetmanager.cloud/token_auth.php").mock(side_effect=_token_auth_response)

    resolved_host, user_token = await exchange_user_token(
        "clinic-auth",
        login="doctor",
        password="doctor-pass-123",
    )

    headers = captured["headers"]
    body = captured["body"]
    assert resolved_host == "https://clinic-auth.vetmanager.cloud"
    assert user_token == "fresh-user-token"
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    assert "x-rest-api-key" not in {key.lower() for key in headers}
    assert b'name="login"' in body
    assert b'doctor' in body
    assert b'name="password"' in body
    assert b'doctor-pass-123' in body
    assert b'name="app_name"' in body
    assert b'vetmanager-mcp' in body


@pytest.mark.asyncio
@respx.mock
async def test_exchange_user_token_preserves_password_whitespace():
    """Whitespace in password is sent as-is; only emptiness is rejected."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-auth-space").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-auth-space.vetmanager.cloud"}})
    )

    captured: dict[str, object] = {}

    def _token_auth_response(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"data": {"token": "fresh-user-token"}})

    respx.post("https://clinic-auth-space.vetmanager.cloud/token_auth.php").mock(
        side_effect=_token_auth_response
    )

    _, user_token = await exchange_user_token(
        "clinic-auth-space",
        login="doctor",
        password="  secret-pass  ",
    )

    assert user_token == "fresh-user-token"
    assert b"  secret-pass  " in captured["body"]


@pytest.mark.asyncio
async def test_validate_domain_api_key_connection_uses_shared_pool_and_retries_transient_503(monkeypatch):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            if self.calls < 3:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json={"data": []})

    fake_client = FakeClient()
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    reset_service_metrics()

    resolved = await validate_domain_api_key_connection(
        "clinic-a",
        "secret-key",
        resolved_host="https://clinic-a.vetmanager.cloud",
    )

    metrics = snapshot_service_metrics()
    assert resolved == "https://clinic-a.vetmanager.cloud"
    assert fake_client.calls == 3
    assert len(sleep_delays) == 2
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|error"] == 2
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|success"] == 1
    assert metrics["upstream_failures_total"]["vetmanager_api_probe|http_503"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_error", "failure_reason"),
    [
        (httpx.ReadTimeout("slow response"), "timeout"),
        (httpx.ConnectError("connection reset"), "connect_error"),
    ],
)
async def test_connection_get_retries_transport_failures_per_attempt(
    monkeypatch,
    caplog,
    first_error,
    failure_reason,
):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            if self.calls == 1:
                raise first_error
            return httpx.Response(200, json={"data": []})

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    reset_service_metrics()

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        resolved = await validate_domain_api_key_connection(
            "clinic-a",
            "secret-key",
            resolved_host="https://clinic-a.vetmanager.cloud",
            account_connection_id=49,
        )

    metrics = snapshot_service_metrics()
    retry_records = [
        record
        for record in caplog.records
        if getattr(record, "event_name", "") == "vetmanager_auth_probe_retry"
    ]
    assert resolved == "https://clinic-a.vetmanager.cloud"
    assert fake_client.calls == 2
    assert len(retry_records) == 1
    assert retry_records[0].attempt == 1
    assert retry_records[0].target == "vetmanager_api_probe"
    assert retry_records[0].error_class == type(first_error).__name__
    assert retry_records[0].account_connection_id == 49
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|error"] == 1
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|success"] == 1
    assert metrics["upstream_failures_total"][f"vetmanager_api_probe|{failure_reason}"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (httpx.ReadTimeout("slow response"), VetmanagerTimeoutError),
        (httpx.ConnectError("connection reset"), VetmanagerError),
    ],
)
async def test_connection_post_does_not_retry_after_possible_delivery(
    monkeypatch,
    error,
    expected_exception,
):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def post(self, url, *, headers=None, files=None):
            self.calls += 1
            raise error

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)

    with pytest.raises(expected_exception):
        await service._request_with_retry(
            "post",
            "https://clinic-a.vetmanager.cloud/token_auth.php",
            target="vetmanager_token_auth",
            headers={},
            files={},
            timeout_message="timeout",
            unavailable_message="unavailable",
        )

    assert fake_client.calls == 1


@pytest.mark.asyncio
async def test_connection_post_retries_connect_timeout_but_not_503(monkeypatch):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.responses = [
                httpx.ConnectTimeout("not connected"),
                httpx.Response(200, json={"data": {"token": "token"}}),
                httpx.Response(503, json={"error": "unavailable"}),
            ]
            self.calls = 0

        async def post(self, url, *, headers=None, files=None):
            self.calls += 1
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    response = await service._request_with_retry(
        "POST",
        "https://clinic-a.vetmanager.cloud/token_auth.php",
        target="vetmanager_token_auth",
        headers={},
        files={},
        timeout_message="timeout",
        unavailable_message="unavailable",
    )
    assert response.status_code == 200
    assert fake_client.calls == 2

    response = await service._request_with_retry(
        "POST",
        "https://clinic-a.vetmanager.cloud/token_auth.php",
        target="vetmanager_token_auth",
        headers={},
        files={},
        timeout_message="timeout",
        unavailable_message="unavailable",
    )
    assert response.status_code == 503
    assert fake_client.calls == 3


@pytest.mark.asyncio
async def test_connection_tls_verification_failure_is_not_retried(monkeypatch):
    import vetmanager_connection_service as service

    tls_cause = ssl.SSLCertVerificationError("certificate verify failed")
    error = httpx.ConnectError("TLS failed")
    error.__cause__ = tls_cause

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            raise error

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)

    with pytest.raises(VetmanagerTlsError):
        await service._request_with_retry(
            "GET",
            "https://clinic-a.vetmanager.cloud/rest/api/user",
            target="vetmanager_api_probe",
            headers={},
            timeout_message="timeout",
            unavailable_message="unavailable",
        )

    assert fake_client.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_exception", "expected_message"),
    [
        (httpx.ReadTimeout("slow response"), VetmanagerTimeoutError, "original timeout"),
        (httpx.ConnectError("connection reset"), VetmanagerError, "original unavailable"),
    ],
)
async def test_connection_budget_stops_retry_without_replacing_last_error(
    monkeypatch,
    caplog,
    error,
    expected_exception,
    expected_message,
):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            raise error

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service, "backoff_seconds", lambda attempt, retry_after=None: 45.0)
    assert service.CONNECTION_REQUEST_BUDGET_SECONDS == 45.0

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        with pytest.raises(expected_exception) as caught:
            await service._request_with_retry(
                "GET",
                "https://clinic-a.vetmanager.cloud/rest/api/user",
                target="vetmanager_api_probe",
                headers={},
                timeout_message="original timeout",
                unavailable_message="original unavailable",
            )

    assert str(caught.value) == expected_message
    assert fake_client.calls == 1
    assert not any(
        getattr(record, "event_name", "") == "vetmanager_auth_probe_retry"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_connection_budget_returns_last_retryable_http_response(monkeypatch, caplog):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            return httpx.Response(
                503,
                headers={"Retry-After": "60"},
                json={"error": "unavailable"},
            )

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        response = await service._request_with_retry(
            "GET",
            "https://clinic-a.vetmanager.cloud/rest/api/user",
            target="vetmanager_api_probe",
            headers={},
            timeout_message="timeout",
            unavailable_message="unavailable",
        )

    assert response.status_code == 503
    assert fake_client.calls == 1
    assert not any(
        getattr(record, "event_name", "") == "vetmanager_auth_probe_retry"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_connection_wall_clock_budget_records_terminal_timeout(monkeypatch, caplog):
    import vetmanager_connection_service as service

    class FakeClient:
        async def get(self, url, *, params=None, headers=None):
            await asyncio.sleep(0.02)
            return httpx.Response(200, json={"data": []})

    async def fake_get_shared_http_client():
        return FakeClient()

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service, "CONNECTION_REQUEST_BUDGET_SECONDS", 0.01, raising=False)
    reset_service_metrics()

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        with pytest.raises(VetmanagerTimeoutError):
            await service._request_with_retry(
                "GET",
                "https://clinic-a.vetmanager.cloud/rest/api/user",
                target="vetmanager_api_probe",
                headers={},
                timeout_message="wall timeout",
                unavailable_message="unavailable",
            )

    metrics = snapshot_service_metrics()
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|error"] == 1
    assert metrics["upstream_failures_total"]["vetmanager_api_probe|timeout"] == 1
    assert sum(
        getattr(record, "event_name", "") == "vetmanager_auth_probe_failed"
        for record in caplog.records
    ) == 1


@pytest.mark.asyncio
async def test_connection_backoff_oversleep_preserves_previous_timeout(monkeypatch, caplog):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            raise httpx.ReadTimeout("previous timeout")

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    real_sleep = asyncio.sleep

    async def oversleep(delay: float) -> None:
        await real_sleep(0.03)

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service, "CONNECTION_REQUEST_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(service, "_CONNECTION_RETRY_MIN_REMAINING_SECONDS", 0.005)
    monkeypatch.setattr(service, "backoff_seconds", lambda attempt, retry_after=None: 0.001)
    monkeypatch.setattr(service.asyncio, "sleep", oversleep)

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        with pytest.raises(VetmanagerTimeoutError) as caught:
            await service._request_with_retry(
                "GET",
                "https://clinic-a.vetmanager.cloud/rest/api/user",
                target="vetmanager_api_probe",
                headers={},
                timeout_message="previous timeout",
                unavailable_message="unavailable",
            )

    assert str(caught.value) == "previous timeout"
    assert fake_client.calls == 1
    assert not any(
        getattr(record, "event_name", "") == "vetmanager_auth_probe_retry"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_connection_last_started_attempt_wins_over_previous_503(monkeypatch, caplog):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(503, json={"error": "unavailable"})
            await asyncio.sleep(0.1)
            return httpx.Response(200, json={"data": []})

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service, "CONNECTION_REQUEST_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr(service, "_CONNECTION_RETRY_MIN_REMAINING_SECONDS", 0.0)
    monkeypatch.setattr(service, "backoff_seconds", lambda attempt, retry_after=None: 0.0)
    reset_service_metrics()

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        with pytest.raises(VetmanagerTimeoutError):
            await service._request_with_retry(
                "GET",
                "https://clinic-a.vetmanager.cloud/rest/api/user",
                target="vetmanager_api_probe",
                headers={},
                timeout_message="last attempt timed out",
                unavailable_message="unavailable",
            )

    metrics = snapshot_service_metrics()
    assert fake_client.calls == 2
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|error"] == 2
    assert metrics["upstream_failures_total"]["vetmanager_api_probe|http_503"] == 1
    assert metrics["upstream_failures_total"]["vetmanager_api_probe|timeout"] == 1


@pytest.mark.asyncio
async def test_connection_external_cancellation_is_not_normalized(monkeypatch):
    import vetmanager_connection_service as service

    class FakeClient:
        async def get(self, url, *, params=None, headers=None):
            raise asyncio.CancelledError

    async def fake_get_shared_http_client():
        return FakeClient()

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)

    with pytest.raises(asyncio.CancelledError):
        await service._request_with_retry(
            "GET",
            "https://clinic-a.vetmanager.cloud/rest/api/user",
            target="vetmanager_api_probe",
            headers={},
            timeout_message="timeout",
            unavailable_message="unavailable",
        )


@pytest.mark.asyncio
async def test_connection_exhausted_503_records_each_attempt_once(monkeypatch, caplog):
    import vetmanager_connection_service as service

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, *, params=None, headers=None):
            self.calls += 1
            return httpx.Response(503, json={"error": "unavailable"})

    fake_client = FakeClient()

    async def fake_get_shared_http_client():
        return fake_client

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(service, "get_shared_http_client", fake_get_shared_http_client)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    reset_service_metrics()

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        response = await service._request_with_retry(
            "get",
            "https://clinic-a.vetmanager.cloud/rest/api/user",
            target="vetmanager_api_probe",
            headers={},
            timeout_message="timeout",
            unavailable_message="unavailable",
        )

    metrics = snapshot_service_metrics()
    assert response.status_code == 503
    assert fake_client.calls == 3
    assert metrics["upstream_requests_total"]["vetmanager_api_probe|error"] == 3
    assert metrics["upstream_failures_total"]["vetmanager_api_probe|http_503"] == 3
    assert sum(
        getattr(record, "event_name", "") == "vetmanager_auth_probe_retry"
        for record in caplog.records
    ) == 2


@pytest.mark.asyncio
async def test_evaluate_connection_health_logs_warning_for_probe_errors(monkeypatch, caplog):
    import vetmanager_connection_service as service

    connection = VetmanagerConnection(
        id=77,
        account_id=1,
        auth_mode="domain_api_key",
        status="active",
        domain="clinic-a",
    )
    connection.set_credentials(
        {"domain": "clinic-a", "api_key": "secret-key"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    async def fake_validate(*args, **kwargs):
        raise VetmanagerTimeoutError("probe timeout")

    monkeypatch.setattr(service, "validate_domain_api_key_connection", fake_validate)

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        status, reason = await evaluate_connection_health(
            connection,
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    assert status == "unknown"
    assert "could not be verified" in reason
    assert any(
        record.levelname == "WARNING"
        and getattr(record, "event_name", "") == "connection_health_failed"
        and getattr(record, "account_connection_id", None) == 77
        for record in caplog.records
    )


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_concurrent_calls_leave_single_active(session_factory):
    """Concurrent saves for one account must not leave multiple ACTIVE rows."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-race").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-race.vetmanager.cloud"}})
    )
    respx.get("https://clinic-race.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async def _save(api_key: str) -> None:
        async with session_factory() as session:
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-race",
                api_key=api_key,
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    await asyncio.gather(_save("key-1"), _save("key-2"))

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(VetmanagerConnection)
                .where(VetmanagerConnection.account_id == 1)
                .order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    active_rows = [row for row in rows if row.status == "active"]
    disabled_rows = [row for row in rows if row.status == "disabled"]
    assert len(rows) == 2
    assert len(active_rows) == 1
    assert len(disabled_rows) == 1


@pytest.mark.asyncio
@respx.mock
async def test_save_user_login_password_connection_persists_token_without_api_key(session_factory):
    """Saving login/password mode should not require or persist an API key."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-login").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-login.vetmanager.cloud"}})
    )
    respx.post("https://clinic-login.vetmanager.cloud/token_auth.php").mock(
        return_value=httpx.Response(200, json={"data": {"token": "user-token-secret"}})
    )
    captured_validation: dict[str, object] = {}

    def _validation_response(request: httpx.Request) -> httpx.Response:
        captured_validation["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})

    respx.get("https://clinic-login.vetmanager.cloud/rest/api/user").mock(side_effect=_validation_response)

    async with session_factory() as session:
        connection = await save_user_login_password_connection(
            session,
            account_id=1,
            domain="clinic-login",
            login="doctor",
            password="doctor-pass-123",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.auth_mode == "user_token"
    assert "user-token-secret" not in stored.encrypted_credentials
    assert "doctor-pass-123" not in stored.encrypted_credentials
    assert "vetmanager-mcp" in stored.get_credentials(encryption_key=TEST_ENCRYPTION_KEY).get("app_name", "")
    headers = {key.lower(): value for key, value in captured_validation["headers"].items()}
    assert headers["x-user-token"] == "user-token-secret"
    assert headers["x-app-name"] == "vetmanager-mcp"
    assert "x-rest-api-key" not in headers


@pytest.mark.asyncio
@respx.mock
async def test_save_user_login_password_connection_concurrent_calls_dedupe_token_issue(session_factory):
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-login-race").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-login-race.vetmanager.cloud"}})
    )
    token_issue_calls = 0

    async def _token_auth_response(request: httpx.Request) -> httpx.Response:
        nonlocal token_issue_calls
        token_issue_calls += 1
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"data": {"token": "shared-user-token"}})

    respx.post("https://clinic-login-race.vetmanager.cloud/token_auth.php").mock(
        side_effect=_token_auth_response
    )
    respx.get("https://clinic-login-race.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async def _save() -> VetmanagerConnection:
        async with session_factory() as session:
            return await save_user_login_password_connection(
                session,
                account_id=1,
                domain="clinic-login-race",
                login="doctor",
                password="doctor-pass-123",
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    first, second = await asyncio.gather(_save(), _save())

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(VetmanagerConnection)
                .where(VetmanagerConnection.account_id == 1)
                .order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    assert token_issue_calls == 1
    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].status == "active"
    credentials = rows[0].get_credentials(encryption_key=TEST_ENCRYPTION_KEY)
    assert credentials["user_token"] == "shared-user-token"


@pytest.mark.asyncio
async def test_save_user_login_password_connection_does_not_coalesce_different_credentials(
    session_factory,
    monkeypatch,
):
    token_issue_calls: list[tuple[str, str, str]] = []

    async def _fake_exchange(domain: str, *, login: str, password: str):
        token_issue_calls.append((domain, login, password))
        await asyncio.sleep(0.05)
        return f"https://{domain}.vetmanager.cloud", f"{domain}-{login}-token"

    async def _fake_validate(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "vetmanager_connection_service.exchange_user_token",
        _fake_exchange,
    )
    monkeypatch.setattr(
        "vetmanager_connection_service.validate_user_token_connection",
        _fake_validate,
    )

    async def _save(domain: str, login: str, password: str) -> VetmanagerConnection:
        async with session_factory() as session:
            return await save_user_login_password_connection(
                session,
                account_id=1,
                domain=domain,
                login=login,
                password=password,
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    await asyncio.gather(
        _save("clinic-login-a", "doctor-a", "pass-a"),
        _save("clinic-login-b", "doctor-b", "pass-b"),
    )

    assert sorted(token_issue_calls) == [
        ("clinic-login-a", "doctor-a", "pass-a"),
        ("clinic-login-b", "doctor-b", "pass-b"),
    ]


@pytest.mark.asyncio
async def test_save_user_login_password_connection_cancelled_waiter_does_not_cancel_shared_prepare(
    session_factory,
    monkeypatch,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def _fake_exchange(domain: str, *, login: str, password: str):
        started.set()
        await release.wait()
        return f"https://{domain}.vetmanager.cloud", "shared-user-token"

    async def _fake_validate(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "vetmanager_connection_service.exchange_user_token",
        _fake_exchange,
    )
    monkeypatch.setattr(
        "vetmanager_connection_service.validate_user_token_connection",
        _fake_validate,
    )

    async def _save() -> VetmanagerConnection:
        async with session_factory() as session:
            return await save_user_login_password_connection(
                session,
                account_id=1,
                domain="clinic-login-shield",
                login="doctor",
                password="doctor-pass-123",
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    first = asyncio.create_task(_save())
    second = asyncio.create_task(_save())
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    connection = await second

    assert connection.auth_mode == "user_token"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.security
async def test_save_domain_api_key_connection_rejects_host_with_path_or_query(session_factory):
    """Billing-resolved host must stay a bare origin before probe requests."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-unsafe").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"url": "https://clinic-unsafe.vetmanager.cloud/nested?x=1"}},
        )
    )

    async with session_factory() as session:
        with pytest.raises(HostResolutionError):
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-unsafe",
                api_key="unsafe-key",
                encryption_key=TEST_ENCRYPTION_KEY,
            )
