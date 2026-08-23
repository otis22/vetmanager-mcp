"""Packaging metadata regressions for flat source-layout runtime installs."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "Dockerfile"

EXPECTED_RUNTIME_INCLUDES = {
    "alembic",
    "auth",
    "resources",
    "tools",
    "vm_transport",
    "server.py",
    "storage.py",
    "tool_access_registry.py",
    "vetmanager_client.py",
    "web.py",
}
NON_RUNTIME_TREES = {"tests", "PRD", "artifacts"}


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_fastmcp_bounds_match_docker_runtime_dependency() -> None:
    pyproject = _pyproject()
    dependencies = set(pyproject["project"]["dependencies"])
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "fastmcp>=3.1.0,<4" in dependencies
    assert '"fastmcp>=3.1.0,<4"' in dockerfile
    assert "fastmcp>=2.0.0" not in dependencies


def test_wheel_target_includes_flat_runtime_sources_not_tests_or_artifacts() -> None:
    pyproject = _pyproject()
    wheel_target = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    only_include = set(wheel_target["only-include"])
    root_modules = {
        path.name
        for path in ROOT.glob("*.py")
        if path.name not in {"conftest.py"}
    }

    missing_expected = sorted(EXPECTED_RUNTIME_INCLUDES - only_include)
    assert not missing_expected, (
        "обязательные runtime-источники "
        f"{', '.join(missing_expected)} не добавлены в wheel allowlist, "
        "добавьте их в pyproject.toml"
    )
    missing_root_modules = sorted(root_modules - only_include)
    assert not missing_root_modules, (
        "модули "
        f"{', '.join(missing_root_modules)} не добавлены в wheel allowlist, "
        "добавьте их в pyproject.toml"
    )
    non_runtime_includes = sorted(NON_RUNTIME_TREES & only_include)
    assert not non_runtime_includes, (
        "не-runtime каталоги "
        f"{', '.join(non_runtime_includes)} не должны входить в wheel allowlist"
    )
    assert wheel_target.get("packages") != ["tools"]


def test_wheel_allowlist_failure_names_missing_root_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = _pyproject()
    wheel_target = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    wheel_target["only-include"].remove("activation_events.py")
    monkeypatch.setattr("tests.test_packaging_metadata._pyproject", lambda: pyproject)

    with pytest.raises(AssertionError, match=r"модули activation_events\.py .*pyproject\.toml"):
        test_wheel_target_includes_flat_runtime_sources_not_tests_or_artifacts()
