#!/usr/bin/env python3
"""Audit runtime inline imports and fail on undocumented cases.

Stage 114b: most inline imports were removed. The small remainder is
intentional and must stay justified:
- cycle break (`secret_manager.py`);
- lazy heavy/optional dependency (`filters.py`, Redis backend);
- package-level lazy tool registration (`tools/__init__.py`);
- CLI-only bootstrap (`scripts/product_metrics_report.py`).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "htmlcov",
    "PRD",
    "tests",
    "venv",
}

ALLOWLIST: dict[tuple[str, str, str], str] = {
    (
        "secret_manager.py",
        "validate_required_secrets",
        "from web_auth import get_web_session_secret",
    ): "Breaks the storage_models -> secret_manager -> web_auth cycle.",
    (
        "filters.py",
        "build_list_query_params",
        "from validators import validate_list_params",
    ): "Avoids pulling validator dependencies into every lightweight filter import path.",
    (
        "rate_limit_backend.py",
        "get_rate_limit_backend",
        "import redis as _redis_lib",
    ): "Redis is optional; import only when REDIS_URL enables the backend.",
    (
        "scripts/product_metrics_report.py",
        "_async_main",
        "from storage import get_session_factory",
    ): "CLI report bootstraps storage only at execution time, not at import time.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.client import register as register_client",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.pet import register as register_pet",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.admission import register as register_admission",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.medical_card import register as register_medical_card",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.invoice import register as register_invoice",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.good import register as register_good",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.user import register as register_user",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.reference import register as register_reference",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.finance import register as register_finance",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.warehouse import register as register_warehouse",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.clinical import register as register_clinical",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.operations import register as register_operations",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
    (
        "tools/__init__.py",
        "register_all",
        "from tools.schedule import register as register_schedule",
    ): "Lazy-register tool modules without importing the full tool graph on package import.",
}


def _iter_python_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def collect_inline_imports(repo_root: Path) -> list[tuple[str, str, int, str]]:
    found: list[tuple[str, str, int, str]] = []
    for path in _iter_python_files(repo_root):
        rel = str(path.relative_to(repo_root))
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        def _walk(node: ast.AST, enclosing: str | None = None) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing = node.name
                for child in node.body:
                    _walk(child, enclosing)
                return
            if enclosing and isinstance(node, (ast.Import, ast.ImportFrom)):
                import_src = ast.get_source_segment(source, node) or ""
                found.append((rel, enclosing, node.lineno, import_src.strip()))
            for child in ast.iter_child_nodes(node):
                _walk(child, enclosing)

        for node in tree.body:
            _walk(node)
    return found


def collect_undocumented_inline_imports(
    repo_root: Path,
) -> list[tuple[str, str, int, str]]:
    undocumented: list[tuple[str, str, int, str]] = []
    for rel, func_name, lineno, import_src in collect_inline_imports(repo_root):
        if (rel, func_name, import_src) not in ALLOWLIST:
            undocumented.append((rel, func_name, lineno, import_src))
    return undocumented


def main(argv: list[str] | None = None) -> int:
    undocumented = collect_undocumented_inline_imports(REPO_ROOT)
    if undocumented:
        print("Undocumented inline imports found:")
        for rel, func_name, lineno, import_src in undocumented:
            print(f"- {rel}:{lineno} in {func_name}: {import_src}")
        return 1

    documented = collect_inline_imports(REPO_ROOT)
    print(
        f"inline-import audit passed: {len(documented)} documented case(s), "
        f"0 undocumented"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
