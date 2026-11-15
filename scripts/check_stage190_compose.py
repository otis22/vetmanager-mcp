#!/usr/bin/env python3
"""Validate the stage 190 production Compose shape on a Docker-capable host."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run Compose validation without emitting interpolated configuration."""
    env = {**os.environ, "GRAFANA_ADMIN_PASSWORD": "stage190-not-default"}
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "--profile", "production", "config"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print(f"Stage 190 Compose validation failed (exit {result.returncode}).")
        return 1
    print("Stage 190 Compose validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
