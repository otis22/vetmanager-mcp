"""Three MCP PostgreSQL pools must leave at least ten of fifty connections free."""

import pytest

from storage import StorageError, validate_mcp_pool_budget


def test_three_worker_pool_budget_accepts_8_plus_5(monkeypatch):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    assert validate_mcp_pool_budget() == (8, 5)


@pytest.mark.parametrize("pool,overflow", [(10, 20), (0, 5), (8, -1), ("bad", 0)])
def test_three_worker_pool_budget_fails_closed(monkeypatch, pool, overflow):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("DB_POOL_SIZE", str(pool))
    monkeypatch.setenv("DB_MAX_OVERFLOW", str(overflow))
    with pytest.raises(StorageError):
        validate_mcp_pool_budget()


def test_compose_slots_set_bounded_pool():
    from pathlib import Path
    import yaml

    services = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text())["services"]
    for name in ("mcp", "mcp2", "mcp3"):
        env = services[name]["environment"]
        assert "MCP_WORKER_SLOTS=3" in env
        assert "DB_POOL_SIZE=8" in env
        assert "DB_MAX_OVERFLOW=5" in env
