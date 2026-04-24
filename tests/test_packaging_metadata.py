"""Packaging metadata regressions for flat source-layout runtime installs."""

from __future__ import annotations

from pathlib import Path
import tomllib


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

    assert EXPECTED_RUNTIME_INCLUDES.issubset(only_include)
    assert root_modules.issubset(only_include)
    assert not (NON_RUNTIME_TREES & only_include)
    assert wheel_target.get("packages") != ["tools"]
