#!/usr/bin/env python3
"""Stage 265.6: inside `tools/`, a `ToolError` is never built by hand.

Every refusal a tool produces is one of two things, and the line that writes it
has to say which:

    ToolInputError(...)    the caller got an argument wrong. No invitation to
                           file a bug report, no Sentry issue.
    reportable_error(...)  everything else — upstream refused, its payload is
                           unusable, or we broke. Worth reporting.

Building `ToolError` directly says nothing, and that silence is what shipped:
validation phrased as "clinic_id must be a positive integer" invited the user
to report a defect in answer to their own typo, from the first day.

The rule has no exceptions, so there is no inventory to keep in sync. The
first draft of this guard did keep one — a list of allowed `raise ToolError`
sites — and external review broke it twice in a minute: three factories in
this repository *return* a ToolError rather than raise it, and an inventory
keyed on per-function counts stays green when one check is retyped while
another is added beside it.

What counts as building it: any call of a name that resolves to `ToolError`,
including an import alias, a call through the module, and a name rebound to
the class. Catching it, annotating with it and asking `isinstance` are not
building it and are left alone.

Known limit, stated rather than hidden: a helper that lives outside `tools/`
and builds a `ToolError` for a tool is not visible here. Three such helpers
exist on purpose — `reportable_error`, the report-hint rebuild in
`agent_feedback_service`, and the redaction rebuild in `privacy_utils`.

Usage:
    ./scripts/check_tool_error_classification.py [path ...]
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_CLASS = "ToolError"
EXCEPTIONS_MODULE = "fastmcp.exceptions"


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    how: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: builds {FORBIDDEN_CLASS} directly ({self.how}). "
            f"Say whose mistake it is: ToolInputError(...) for the caller's, "
            f"reportable_error(...) for anything worth reporting."
        )


class _Scanner(ast.NodeVisitor):
    """Collect the names through which this module can reach ToolError."""

    def __init__(self) -> None:
        # Names bound directly to the class: `ToolError`, `TE`, `_ERROR`.
        self.class_names: set[str] = set()
        # Local name -> the module path it stands for. `import fastmcp as fm`
        # binds `fm` to `fastmcp`, and `fm.exceptions.ToolError` is then the
        # same class reached one dot further out.
        self.module_paths: dict[str, str] = {}
        self.findings: list[tuple[int, str]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            if module == EXCEPTIONS_MODULE and alias.name == FORBIDDEN_CLASS:
                self.class_names.add(alias.asname or alias.name)
            else:
                # `from fastmcp import exceptions as fe`
                self.module_paths[alias.asname or alias.name] = f"{module}.{alias.name}"
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname:
                # `import fastmcp.exceptions as fe`, `import fastmcp as fm`
                self.module_paths[alias.asname] = alias.name
            else:
                # `import fastmcp.exceptions` binds the top package only.
                self.module_paths[alias.name.split(".")[0]] = alias.name.split(".")[0]
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # `_ERROR = ToolError` — the class keeps travelling under a new name.
        self._bind(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # `_ERROR: type[Exception] = ToolError` — the same move, typed.
        if node.value is not None:
            self._bind([node.target], node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._bind([node.target], node.value)
        self.generic_visit(node)

    def _bind(self, targets, value: ast.expr) -> None:
        carries_class = (
            isinstance(value, ast.Name) and value.id in self.class_names
        ) or self._is_class_attribute(value)
        if not carries_class:
            return
        for target in targets:
            if isinstance(target, ast.Name):
                self.class_names.add(target.id)

    def visit_Call(self, node: ast.Call) -> None:
        how = self._how_it_reaches_the_class(node.func)
        if how is not None:
            self.findings.append((node.lineno, how))
        self.generic_visit(node)

    def _how_it_reaches_the_class(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            if func.id == FORBIDDEN_CLASS:
                return "by name"
            if func.id in self.class_names:
                return f"through the name {func.id!r}"
            return None
        if self._is_class_attribute(func):
            return f"through {ast.unparse(func)}"
        return None

    def _is_class_attribute(self, node: ast.expr) -> bool:
        """`fe.ToolError`, `fastmcp.exceptions.ToolError`, `fm.exceptions.ToolError`."""
        if not isinstance(node, ast.Attribute) or node.attr != FORBIDDEN_CLASS:
            return False
        return self._module_path(node.value) == EXCEPTIONS_MODULE

    def _module_path(self, node: ast.expr) -> str | None:
        """Expand the leading local name of a dotted path into its module."""
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        head = self.module_paths.get(node.id, node.id)
        parts.append(head)
        return ".".join(reversed(parts))


def scan_file(path: Path) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    scanner = _Scanner()
    scanner.visit(tree)
    return [Finding(path, line, how) for line, how in sorted(scanner.findings)]


def scan_paths(paths) -> list[Finding]:
    findings: list[Finding] = []
    for entry in paths:
        entry = Path(entry)
        files = sorted(entry.rglob("*.py")) if entry.is_dir() else [entry]
        for file_path in files:
            findings.extend(scan_file(file_path))
    return findings


def main(argv: list[str]) -> int:
    paths = argv[1:] or [Path(__file__).resolve().parents[1] / "tools"]
    findings = scan_paths(paths)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
