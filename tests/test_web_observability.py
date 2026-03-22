"""HTTP coverage for health and readiness probe endpoints."""

from pathlib import Path

import httpx
import pytest

import storage
from server import mcp
from storage import Base, create_database_engine
from web_security import reset_web_security_state


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "web-observability.db"
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
async def test_healthz_returns_liveness_contract(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "probe": "liveness",
        "service": "vetmanager-mcp",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_readyz_returns_readiness_contract_when_storage_is_available(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "probe": "readiness",
        "service": "vetmanager-mcp",
        "checks": {
            "storage": {
                "status": "ok",
                "reason": "ok",
            }
        },
    }

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_readyz_returns_503_when_storage_is_unavailable(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    await engine.dispose()
    storage.reset_storage_state()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/vetmanager")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "probe": "readiness",
        "service": "vetmanager-mcp",
        "checks": {
            "storage": {
                "status": "failed",
                "reason": "storage_unavailable",
            }
        },
    }

    storage.reset_storage_state()
