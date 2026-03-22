"""Regression coverage for Prometheus-compatible metrics export."""

from pathlib import Path

import httpx
import pytest

import storage
from server import mcp
from service_metrics import (
    record_auth_failure,
    record_http_request,
    record_upstream_failure,
    render_prometheus_metrics,
    reset_service_metrics,
)
from storage import Base, create_database_engine
from web_security import reset_web_security_state


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "prometheus-metrics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def test_render_prometheus_metrics_serializes_registry_snapshot():
    reset_service_metrics()
    record_http_request(route="/healthz", method="GET", status_code=200, duration_seconds=0.123)
    record_auth_failure(source="bearer_header", reason="missing_authorization")
    record_upstream_failure(target="billing_api", reason="timeout")

    metrics_text = render_prometheus_metrics()

    assert "# TYPE vetmanager_http_requests_total counter" in metrics_text
    assert 'vetmanager_http_requests_total{route="/healthz",method="GET",status_code="200"} 1' in metrics_text
    assert 'vetmanager_http_request_latency_seconds_count{route="/healthz",method="GET"} 1' in metrics_text
    assert 'vetmanager_auth_failures_total{source="bearer_header",reason="missing_authorization"} 1' in metrics_text
    assert 'vetmanager_upstream_failures_total{target="billing_api",reason="timeout"} 1' in metrics_text


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text_response(tmp_path: Path, monkeypatch):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/healthz")
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert 'vetmanager_http_requests_total{route="/healthz",method="GET",status_code="200"} 1' in response.text
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]

    await engine.dispose()
    storage.reset_storage_state()
