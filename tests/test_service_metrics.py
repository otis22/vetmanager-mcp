"""Regression coverage for process-local service metrics registry."""

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

import request_auth
import auth.request as auth_request
import storage
from exceptions import AuthError, VetmanagerTimeoutError
from server import mcp
from service_metrics import reset_service_metrics, snapshot_service_metrics
from storage import Base, create_database_engine
from tests.runtime_factories import make_client_with_resolved_runtime
from web_security import reset_web_security_state


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "service-metrics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_health_and_readiness_requests_update_http_metrics(tmp_path: Path, monkeypatch):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/healthz")
        await client.get("/readyz")

    snapshot = snapshot_service_metrics()
    assert snapshot["http_requests_total"]["/healthz|GET|200"] == 1
    assert snapshot["http_requests_total"]["/readyz|GET|200"] == 1
    assert snapshot["http_request_latency_seconds"]["/healthz|GET"]["count"] == 1
    assert snapshot["http_request_latency_seconds"]["/readyz|GET"]["count"] == 1

    await engine.dispose()
    storage.reset_storage_state()


def test_bearer_header_failures_update_auth_metrics():
    reset_service_metrics()

    with patch.object(auth_request, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError):
            request_auth.get_bearer_token()

    with patch.object(auth_request, "_get_request_headers", return_value={"authorization": "Basic abc"}):
        with pytest.raises(AuthError):
            request_auth.get_bearer_token()

    snapshot = snapshot_service_metrics()
    assert snapshot["auth_failures_total"]["bearer_header|missing_authorization"] == 1
    assert snapshot["auth_failures_total"]["bearer_header|invalid_authorization"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_billing_timeout_updates_upstream_failure_metrics():
    reset_service_metrics()
    route = respx.get("https://billing-api.vetmanager.cloud/host/metrics-clinic")
    route.mock(side_effect=httpx.TimeoutException("timeout"))
    client = make_client_with_resolved_runtime("metrics-clinic", "metrics-key")

    with pytest.raises(VetmanagerTimeoutError):
        await client.get("/rest/api/client")

    snapshot = snapshot_service_metrics()
    assert snapshot["upstream_failures_total"]["billing_api|timeout"] == 1
