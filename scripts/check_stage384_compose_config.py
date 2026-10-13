#!/usr/bin/env python3
"""Validate normalized production Compose limits before stage 384 release."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2
EXPECTED = {
    "postgres": (1, 1024 * MIB),
    "redis": (0.5, 512 * MIB),
    "mcp": (1, 640 * MIB),
    "mcp2": (1, 640 * MIB),
    "mcp3": (1, 640 * MIB),
    "prometheus": (0.5, 768 * MIB),
    "grafana": (0.5, 512 * MIB),
}


def main() -> int:
    result = subprocess.run(
        ["docker", "compose", "--profile", "production", "config", "--format", "json"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    services = json.loads(result.stdout)["services"]
    for name, (cpus, memory) in EXPECTED.items():
        service = services[name]
        limits = service["deploy"]["resources"]["limits"]
        assert float(limits["cpus"]) == cpus, name
        assert int(limits["memory"]) == memory, name
        if name in {"prometheus", "grafana"}:
            assert int(service["mem_limit"]) == memory, name
    command = services["postgres"]["command"]
    for setting in ("shared_buffers=256MB", "effective_cache_size=512MB", "work_mem=4MB"):
        assert setting in command, setting
    print("stage 384 normalized Compose limits and PostgreSQL settings: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
