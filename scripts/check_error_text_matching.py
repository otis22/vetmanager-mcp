#!/usr/bin/env python3
"""Stage 265.2: forbid deciding on our own error messages by their wording.

An exception we raise carries a message written for a person. The moment code
branches on a fragment of that message, the message stops being editable: the
next person to improve the wording silently changes behaviour, and no test
fails, because tests are edited together with the text.

The rule is about *our* exceptions:

  forbidden  — ToolError, AuthError and their subclasses. We write those
               words and we rewrite them. Branch on `error_code`, on the
               exception type, or on an attribute instead.
  allowed    — VetmanagerError. That text is the upstream contract and often
               the only signal there is. It must live in a named classifier
               function so the dependency is visible and testable, not sit
               inline in a handler.

`AuthError` subclasses `VetmanagerError`, so it is checked first — otherwise
the rule would let itself through.

Tests are not scanned: asserting on a message is exactly what they are for.

Usage:
    ./scripts/check_error_text_matching.py [path ...]
"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OUR_EXCEPTIONS = frozenset({
    "ToolError",
    "ToolInputError",
    "AuthChallengeToolError",
    "ScopeDeniedToolError",
    "AuthError",
})
UPSTREAM_EXCEPTIONS = frozenset({"VetmanagerError"})
TEXT_METHODS = frozenset({"lower", "upper", "strip", "startswith", "endswith", "find", "split"})
SKIP_DIRS = ("tests/", "alembic/", ".venv/", "scripts/check_error_text_matching.py")
_WALK_EXCLUDED_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules", "htmlcov"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    name: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.detail} (exception '{self.name}')"


def _tracked_python_files(repo_root: Path) -> list[Path]:
    """Python sources to scan, from git when it is there and by walk when not.

    The test container has no git, and this check runs from the test suite —
    a hard dependency on git would make it silently unrunnable exactly where
    it is supposed to run.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
        )
        names = [name for name in result.stdout.decode().split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        names = [
            str(path.relative_to(repo_root))
            for path in repo_root.rglob("*.py")
            if not any(part in _WALK_EXCLUDED_DIRS for part in path.parts)
        ]
    return [
        repo_root / name
        for name in names
        if not any(name.startswith(skip) or name == skip for skip in SKIP_DIRS)
    ]


class _Scanner(ast.NodeVisitor):
    """Flag decisions made on the wording of one of our own exceptions.

    Reading the text is fine — it gets shown to people, redacted, re-raised.
    What breaks is *branching* on it, so only text that reaches a condition
    counts. Names are tracked per handler: `exc` in one `except` block has
    nothing to do with `exc` in the next one.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self._scopes: list[dict[str, str]] = [{}]

    def _bound(self, name: str) -> str | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        scope: dict[str, str] = {}
        if node.name:
            for type_name in _exception_names(node.type):
                if type_name in OUR_EXCEPTIONS:
                    scope[node.name] = type_name
                    break
            else:
                # A name rebound to something else must not inherit an outer
                # binding — that was the first version's mistake.
                scope[node.name] = ""
        self._scopes.append(scope)
        for child in node.body:
            self.visit(child)
        self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        scope: dict[str, str] = {}
        for arg in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
            for type_name in _exception_names(arg.annotation):
                if type_name in OUR_EXCEPTIONS:
                    scope[arg.arg] = type_name
                    break
        self._scopes.append(scope)
        for child in node.body:
            self.visit(child)
        self._scopes.pop()

    # ── conditions are where a decision happens ──────────────────────────
    def visit_If(self, node: ast.If) -> None:
        self._check_condition(node.test)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_condition(node.test)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._check_condition(node.test)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        # `return str(exc).startswith(...)` is a decision the caller acts on.
        if node.value is not None and _is_boolean_shape(node.value):
            self._check_condition(node.value)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._check_condition(node.test)
        self.generic_visit(node)

    def _check_condition(self, test: ast.expr) -> None:
        for node in ast.walk(test):
            name, how = self._text_read(node)
            if name is None:
                continue
            exception = self._bound(name)
            if exception:
                self.findings.append(Finding(
                    self.path, getattr(node, "lineno", 0), exception,
                    f"decides on the wording of our own message ({how})",
                ))

    def _text_read(self, node: ast.AST) -> tuple[str | None, str]:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"str", "repr"} and node.args:
                return _read_name(node.args[0]), f"{node.func.id}()"
        if isinstance(node, ast.Attribute) and node.attr == "args":
            return _read_name(node.value), ".args"
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "args":
                return _read_name(value.value), ".args[...]"
        return None, ""


def _is_boolean_shape(node: ast.expr) -> bool:
    if isinstance(node, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in TEXT_METHODS
    return False


def _exception_names(node: ast.expr | None) -> list[str]:
    """Names in `except X as e` or an annotation, including tuples of them."""
    if node is None:
        return []
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _exception_names(element)]
    return []


def _read_name(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def scan_source(source: str, path: str) -> list[Finding]:
    scanner = _Scanner(path)
    scanner.visit(ast.parse(source))
    return scanner.findings


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    paths = [Path(arg) for arg in argv[1:]] or _tracked_python_files(repo_root)
    findings: list[Finding] = []
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            findings.extend(scan_source(source, str(path.relative_to(repo_root))))
        except SyntaxError:
            continue
    if findings:
        print("Our own error messages must not be parsed for meaning:")
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nBranch on error_code, on the exception type, or on an attribute. "
            "Upstream text (VetmanagerError) stays allowed inside a named classifier."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
