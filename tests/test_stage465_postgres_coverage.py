"""Stage 465 guards for mandatory PostgreSQL oracle ownership."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from scripts.check_stage424_postgres_results import REQUIRED_FILES


def test_stage408_is_collected_by_postgres_gate() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m",
         "postgres", "tests/test_stage408_postgres.py"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "tests/test_stage408_postgres.py::test_postgres_rating_upsert_and_late_original" in result.stdout


def test_stage408_is_required_in_postgres_result_gate() -> None:
    assert "test_stage408_postgres" in REQUIRED_FILES


def test_stage153_concurrency_oracle_is_collected_by_postgres_gate() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m",
         "postgres", "tests/test_stage153_review_followup.py"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "test_f4_concurrent_create_feedback_report_no_lost_update_postgres_only" in result.stdout


def test_stage153_concurrency_oracle_is_required() -> None:
    assert "test_stage153_review_followup" in REQUIRED_FILES


def test_postgres_ci_supplies_isolated_stage408_database() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/test.yml").read_text())
    steps = workflow["jobs"]["postgres-activation-telemetry"]["steps"]
    create = next(step for step in steps if step.get("name") == "Create isolated stage 408 database")
    run = next(step for step in steps if step.get("name") == "Run mandatory PostgreSQL regression contour")
    assert "CREATE DATABASE vetmanager_stage408" in create["run"]
    assert "STAGE408_PG_URL=" in run["run"]
    assert not create.get("if") and not create.get("continue-on-error")
    assert not run.get("if") and not run.get("continue-on-error")
