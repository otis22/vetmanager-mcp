"""Stage 384 guards for the production ceilings, Uvicorn boot path and 385 budget."""

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_production_resources_and_postgres_settings():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    expected = {
        "postgres": ("1", "1G"),
        "redis": ("0.5", "512M"),
        "mcp": ("1", "640M"),
        "mcp2": ("1", "640M"),
        "mcp3": ("1", "640M"),
        "prometheus": ("0.5", "768M"),
        "grafana": ("0.5", "512M"),
    }
    for name, (cpus, memory) in expected.items():
        service = services[name]
        limits = service["deploy"]["resources"]["limits"]
        assert float(limits["cpus"]) == float(cpus)
        assert limits["memory"].upper() == memory.upper()
        if name in {"prometheus", "grafana"}:
            assert service["mem_limit"].upper() == memory.upper()
    command = services["postgres"]["command"]
    assert "shared_buffers=256MB" in command
    assert "effective_cache_size=512MB" in command
    assert "work_mem=4MB" in command


def test_uvicorn_boot_uses_standard_extras_and_loop_factory(monkeypatch):
    import server

    dockerfile = (ROOT / "Dockerfile").read_text()
    metadata = (ROOT / "pyproject.toml").read_text()
    assert '"uvicorn[standard]==0.42.0"' in dockerfile
    assert '"uvicorn[standard]==0.42.0"' in metadata
    observed = {}

    class Config:
        def __init__(self, _app, **kwargs):
            observed["config"] = kwargs

    class UvicornServer:
        def __init__(self, *_args, **kwargs):
            observed["server"] = kwargs

        def run(self):
            observed["ran"] = True

    monkeypatch.setattr(server.uvicorn, "Config", Config)
    monkeypatch.setattr(server, "_DrainingUvicornServer", UvicornServer)
    server._run_http_server(transport="streamable-http", host="127.0.0.1", port=8000, path="/mcp")
    assert observed["ran"]
    assert observed["config"]["ws"] == "websockets-sansio"
    assert observed["server"]["path"] == "/mcp"


def test_three_worker_budget_rejects_old_mcp_limit():
    from scripts.check_stage384_memory_budget import fits_three_workers

    assert fits_three_workers(peak_rss_bytes=450 * 1024**2, reserve_bytes=512 * 1024**2)
    assert not fits_three_workers(peak_rss_bytes=600 * 1024**2, reserve_bytes=512 * 1024**2)
    assert not fits_three_workers(peak_rss_bytes=450 * 1024**2, reserve_bytes=512 * 1024**2,
                                  limit_bytes=512 * 1024**2)
