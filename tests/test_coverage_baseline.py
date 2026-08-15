"""Regression checks for the non-gating coverage baseline configuration."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_coverage_baseline_measures_product_code_without_threshold() -> None:
    config = ConfigParser()
    config.read(PROJECT_ROOT / ".coveragerc")

    assert config.get("run", "source") == "."
    omit = config.get("run", "omit")
    assert "tests/*" in omit
    assert "scripts/*" in omit
    assert "alembic/*" in omit
    assert not config.has_option("report", "fail_under")


def test_default_runner_writes_terminal_and_xml_coverage_reports() -> None:
    runner = (PROJECT_ROOT / "scripts/run_default_test_suite.py").read_text()

    assert '"--cov"' in runner
    assert '"--cov-report=term-missing:skip-covered"' in runner
    assert '"--cov-report=xml:coverage.xml"' in runner
