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

Known limits, stated rather than hidden. A helper outside the scanned files
that builds the class for a tool is invisible here; three such helpers exist on
purpose — `reportable_error`, the report-hint rebuild in
`agent_feedback_service`, and the redaction rebuild in `privacy_utils`. And the
class can still be reached by `vars(builtins)["ValueError"]`,
`operator.attrgetter`, or `__builtins__` — the external review that found the
`getattr` route judged those an exercise rather than anything anyone writes
here, and closing them would cost more reading than they buy. The alias
imported from a neighbouring module *is* something people write, so it is
resolved across the scanned files.

Stage 266 added `ValueError` to the same rule, for the same reason: a caller's
mistyped date raised one, nothing distinguished it from a broken payload, and
Sentry opened an issue about somebody's typo.

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
# Stage 266: `ValueError` in these files meant three things at once — the
# caller's typo, broken data, and a programmer error — and the first of those
# opened a Sentry issue for somebody's mistyped date. It is a builtin, so it
# needs no import to reach; the rule is the same either way.
FORBIDDEN_BUILTIN = "ValueError"
REPLACEMENTS = (
    "ToolInputError(...) for the caller's mistake, "
    "reportable_error(...) for anything worth reporting, "
    "invariant_error(...) for a state our own code should have prevented"
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    how: str

    what: str = FORBIDDEN_CLASS

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: builds {self.what} directly ({self.how}). "
            f"Say whose mistake it is: {REPLACEMENTS}."
        )


class _Scanner(ast.NodeVisitor):
    """Collect the names through which this module can reach ToolError."""

    def __init__(self, known_aliases: dict[str, dict[str, str]] | None = None) -> None:
        # What other scanned modules call the class, keyed by module name.
        self.known_aliases = known_aliases or {}
        # Names bound directly to the class: `ToolError`, `TE`, `_ERROR`.
        self.class_names: set[str] = set()
        # Local name -> the module path it stands for. `import fastmcp as fm`
        # binds `fm` to `fastmcp`, and `fm.exceptions.ToolError` is then the
        # same class reached one dot further out.
        self.module_paths: dict[str, str] = {}
        # Names bound to the builtin: `ValueError`, or anything it was copied to.
        self.builtin_names: set[str] = set()
        self.findings: list[tuple[int, str, str]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            if module == EXCEPTIONS_MODULE and alias.name == FORBIDDEN_CLASS:
                self.class_names.add(alias.asname or alias.name)
            else:
                exported = self.known_aliases.get(module.rsplit(".", 1)[-1], {})
                carries = exported.get(alias.name)
                if carries == FORBIDDEN_CLASS:
                    self.class_names.add(alias.asname or alias.name)
                elif carries == FORBIDDEN_BUILTIN:
                    self.builtin_names.add(alias.asname or alias.name)
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
        carries_builtin = (
            isinstance(value, ast.Name)
            and (value.id == FORBIDDEN_BUILTIN or value.id in self.builtin_names)
        ) or self._getattr_name(value) == FORBIDDEN_BUILTIN
        if self._getattr_name(value) == FORBIDDEN_CLASS:
            carries_class = True
        if not (carries_class or carries_builtin):
            return
        for target in targets:
            if isinstance(target, ast.Name):
                if carries_class:
                    self.class_names.add(target.id)
                else:
                    self.builtin_names.add(target.id)

    def visit_Call(self, node: ast.Call) -> None:
        if self._getattr_name(node.func) == FORBIDDEN_CLASS:
            self.findings.append((node.lineno, "through getattr", FORBIDDEN_CLASS))
            self.generic_visit(node)
            return
        how = self._how_it_reaches_the_class(node.func)
        if how is not None:
            self.findings.append((node.lineno, how, FORBIDDEN_CLASS))
        else:
            how = self._how_it_reaches_the_builtin(node.func)
            if how is not None:
                self.findings.append((node.lineno, how, FORBIDDEN_BUILTIN))
        self.generic_visit(node)

    def _how_it_reaches_the_builtin(self, func: ast.expr) -> str | None:
        if self._getattr_name(func) == FORBIDDEN_BUILTIN:
            return "through getattr"
        if isinstance(func, ast.Name):
            if func.id == FORBIDDEN_BUILTIN:
                return "by name"
            if func.id in self.builtin_names:
                return f"through the name {func.id!r}"
            return None
        # `builtins.ValueError`, `bt.ValueError`
        if isinstance(func, ast.Attribute) and func.attr == FORBIDDEN_BUILTIN:
            return f"through {ast.unparse(func)}"
        return None

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

    @staticmethod
    def _getattr_name(node: ast.expr) -> str | None:
        """`getattr(builtins, "ValueError")` — the class, spelled sideways."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            return None
        if node.func.id != "getattr" or len(node.args) < 2:
            return None
        wanted = node.args[1]
        return wanted.value if isinstance(wanted, ast.Constant) and isinstance(wanted.value, str) else None

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
    return scan_paths([path])


def _exported_aliases(files) -> dict[str, dict[str, str]]:
    """Module-level names that stand for a forbidden class, per module.

    `_ERROR = ValueError` in one file and `from tools.helpers import _ERROR` in
    the next is how a rule like this gets walked past without anybody meaning
    to.
    """
    exported: dict[str, dict[str, str]] = {}
    for file_path in files:
        scanner = _scan(file_path)
        if scanner is None:
            continue
        names = {name: FORBIDDEN_CLASS for name in scanner.class_names}
        names.update({name: FORBIDDEN_BUILTIN for name in scanner.builtin_names})
        names.pop(FORBIDDEN_CLASS, None)
        if names:
            exported[file_path.stem] = names
    return exported


def _scan(path: Path, known_aliases: dict[str, dict[str, str]] | None = None) -> "_Scanner | None":
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return None
    scanner = _Scanner(known_aliases or {})
    scanner.visit(tree)
    return scanner


def scan_paths(paths) -> list[Finding]:
    files: list[Path] = []
    for entry in paths:
        entry = Path(entry)
        files.extend(sorted(entry.rglob("*.py")) if entry.is_dir() else [entry])

    known_aliases = _exported_aliases(files)
    findings: list[Finding] = []
    for file_path in files:
        scanner = _scan(file_path, known_aliases)
        if scanner is None:
            continue
        findings.extend(
            Finding(file_path, line, how, what) for line, how, what in sorted(scanner.findings)
        )
    return findings


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    paths = argv[1:] or [root / "tools", root / "validators.py"]
    findings = scan_paths(paths)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
