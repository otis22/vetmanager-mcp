import httpx
import pytest

import shutdown_state
import storage
from server import SHUTDOWN_STEP_TIMEOUT_SECONDS, _DrainingUvicornServer, mcp


@pytest.mark.asyncio
async def test_readyz_draining_but_healthz_remains_liveness(tmp_path, monkeypatch):
    database_path = tmp_path / "stage230.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    shutdown_state.reset_draining()
    engine = storage.create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        shutdown_state.begin_draining()
        ready = await client.get("/readyz")
        health = await client.get("/healthz")
    assert ready.status_code == 503
    assert ready.json()["checks"]["storage"]["reason"] == "shutting_down"
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    shutdown_state.reset_draining()
    await engine.dispose()


def test_uvicorn_signal_handler_sets_draining_before_parent(monkeypatch):
    shutdown_state.reset_draining()
    observed = []

    def parent_handler(self, sig, frame):
        observed.append(shutdown_state.is_draining())

    monkeypatch.setattr("uvicorn.Server.handle_exit", parent_handler)
    _DrainingUvicornServer.handle_exit(object.__new__(_DrainingUvicornServer), 15, None)
    assert observed == [True]
    shutdown_state.reset_draining()


def test_shutdown_budget_fits_docker_cleanup_window():
    assert SHUTDOWN_STEP_TIMEOUT_SECONDS == 3
    assert SHUTDOWN_STEP_TIMEOUT_SECONDS * 5 == 15
