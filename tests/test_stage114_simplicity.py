"""Stage 114: simplicity debt — F2 inline imports gone.

Regression tests that ensure `service_metrics` and `resources._aggregation`
do not grow inline imports again.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _inline_imports_in_functions(module_path: Path) -> list[tuple[str, int]]:
    """Return (function_name, line_number) for every import inside a
    FunctionDef or AsyncFunctionDef body (top-level imports inside the
    module body are NOT included)."""
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    found: list[tuple[str, int]] = []

    def _walk(node, enclosing: str | None = None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing = node.name
            for child in node.body:
                _walk(child, enclosing)
            return
        if enclosing is not None and isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append((enclosing, node.lineno))
        for child in ast.iter_child_nodes(node):
            _walk(child, enclosing)

    for node in tree.body:
        _walk(node, None)
    return found


def test_service_metrics_has_no_inline_imports():
    """Regression for stage 114.F2: `import time` and `REQUEST_CACHE` both
    at module scope now; `instrument_call` + `render_prometheus_metrics`
    no longer re-import on every call."""
    path = REPO_ROOT / "service_metrics.py"
    found = _inline_imports_in_functions(path)
    assert not found, (
        f"service_metrics.py must have no inline imports (F2). Found: {found}"
    )


def test_resources_aggregation_has_no_inline_imports():
    """Regression for stage 114.F2: exceptions + RUNTIME_LOGGER +
    get_current_request_context all at module scope; duplicate
    `from exceptions import AuthError` (line 96) removed."""
    path = REPO_ROOT / "resources" / "_aggregation.py"
    found = _inline_imports_in_functions(path)
    assert not found, (
        f"resources/_aggregation.py must have no inline imports (F2). Found: {found}"
    )
