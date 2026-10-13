"""Stage 385.2a1: production slots share durable data within a 3 CPU/2 GiB cap."""

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
SLOTS = ("mcp", "mcp2", "mcp3")


def test_three_immutable_mcp_slots_with_shared_data_and_bounded_resources():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert all(name in services for name in SLOTS)
    slots = [services[name] for name in SLOTS]
    assert sum(float(s["deploy"]["resources"]["limits"]["cpus"]) for s in slots) <= 3
    assert all(s["deploy"]["resources"]["limits"]["memory"] == "640M" for s in slots)
    assert {s["image"] for s in slots} == {"vetmanager-mcp"}
    assert all("WEB_SESSION_SECRET" in s["environment"] for s in slots)
    assert all("STORAGE_ENCRYPTION_KEY" in s["environment"] for s in slots)
    assert {s["ports"][0] for s in slots} == {
        "127.0.0.1:${PORT:-8000}:8000",
        "127.0.0.1:8001:8000",
        "127.0.0.1:8002:8000",
    }
    data_mounts = []
    for slot in slots:
        assert all(not m.endswith(":/app") for m in slot["volumes"])
        data_mounts.append(next(m.split(":")[0] for m in slot["volumes"] if m.endswith(":/app/data")))
    assert len(set(data_mounts)) == 1


def test_production_build_context_excludes_local_secrets():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    assert "COPY . ." in dockerfile
    patterns = (root / ".dockerignore").read_text().splitlines()
    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "!.env.example" in patterns
    assert ".git" in patterns
    assert "data/" in patterns
    assert "*.db" in patterns
    assert "*.db.*" in patterns
    assert ".feedback_fingerprint_pepper.*" in patterns
