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
# Marker for "upstream text, read where it should not be read".
_INLINE_UPSTREAM = "VetmanagerError (inline)"
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
        self.text_reading_helpers: set[str] = set()
        # name -> exception type it is bound to
        self._scopes: list[dict[str, str]] = [{}]
        # name -> exception type whose *message* it holds, after `m = str(exc)`
        self._text_scopes: list[dict[str, str]] = [{}]

    def _bound(self, name: str) -> str | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def _holds_text(self, name: str) -> str | None:
        for scope in reversed(self._text_scopes):
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
                if type_name in UPSTREAM_EXCEPTIONS:
                    # Upstream wording is a real signal, but reading it inline
                    # hides the dependency: the branch quietly relies on a
                    # sentence Vetmanager may reword. Allowed in a named
                    # classifier, where it is visible and testable.
                    scope[node.name] = _INLINE_UPSTREAM
                    break
            else:
                # A name rebound to something else must not inherit an outer
                # binding — that was the first version's mistake.
                scope[node.name] = ""
        self._scopes.append(scope)
        self._text_scopes.append({})
        for child in node.body:
            self.visit(child)
        self._text_scopes.pop()
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
        self._text_scopes.append({})
        for child in node.body:
            self.visit(child)
        self._text_scopes.pop()
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

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._check_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._check_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._check_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._check_comprehension(node)

    def _check_comprehension(self, node: ast.expr) -> None:
        for generator in getattr(node, "generators", []):
            for condition in generator.ifs:
                self._check_condition(condition)
        self.generic_visit(node)

    def _check_condition(self, test: ast.expr) -> None:
        for node in ast.walk(test):
            if isinstance(node, ast.Name):
                # `if "x" in message` where message came from str(exc)
                carried = self._holds_text(node.id)
                if carried:
                    self.findings.append(Finding(
                        self.path, getattr(node, "lineno", 0), carried,
                        "decides on the wording of our own message (via a local)",
                    ))
                continue
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.text_reading_helpers:
                    for argument in node.args:
                        argument_name = _read_name(argument)
                        if argument_name and self._bound(argument_name):
                            self.findings.append(Finding(
                                self.path, getattr(node, "lineno", 0),
                                self._bound(argument_name) or "",
                                f"hands our exception to '{node.func.id}', which decides on its wording",
                            ))
            name, how = self._text_read(node)
            if name is None:
                continue
            exception = self._bound(name)
            if exception:
                self.findings.append(Finding(
                    self.path, getattr(node, "lineno", 0), exception,
                    f"decides on the wording of our own message ({how})",
                ))

    def visit_Assign(self, node: ast.Assign) -> None:
        """`message = str(exc)` carries the wording into another name.

        Without this the rule catches only the shortest spelling, and the
        natural one — assign, then test — walks straight through.
        """
        name, _ = self._text_read(node.value)
        if name and self._bound(name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._text_scopes[-1][target.id] = self._bound(name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            name, _ = self._text_read(node.value)
            if name and self._bound(name) and isinstance(node.target, ast.Name):
                self._text_scopes[-1][node.target.id] = self._bound(name)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        name, _ = self._text_read(node.value)
        if name and self._bound(name) and isinstance(node.target, ast.Name):
            self._text_scopes[-1][node.target.id] = self._bound(name)
        self.generic_visit(node)

    def _text_read(self, node: ast.AST) -> tuple[str | None, str]:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"str", "repr", "format"} and node.args:
                return _read_name(node.args[0]), f"{node.func.id}()"
        if isinstance(node, ast.Attribute) and node.attr == "args":
            return _read_name(node.value), ".args"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                if node.args[1].value in {"args", "message"}:
                    return _read_name(node.args[0]), f'getattr(..., "{node.args[1].value}")'
        if isinstance(node, ast.IfExp):
            # `msg = str(exc) if flag else ""` still ends up holding the text.
            for branch in (node.body, node.orelse):
                name, how = self._text_read(branch)
                if name:
                    return name, f"conditional/{how}"
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "args":
                return _read_name(value.value), ".args[...]"
        # f"{exc}" renders the message just as str() does.
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    name = _read_name(part.value)
                    if name:
                        return name, "f-string"
                    inner, how = self._text_read(part.value)
                    if inner:
                        return inner, f"f-string/{how}"
        # "%s" % exc does too.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            for operand in (node.right,):
                name = _read_name(operand)
                if name:
                    return name, "%-format"
                if isinstance(operand, ast.Tuple):
                    for element in operand.elts:
                        element_name = _read_name(element)
                        if element_name:
                            return element_name, "%-format"
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
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # `exc: "ToolError"` is the same statement, just quoted.
        return [node.value.strip().split("[")[0].split(".")[-1]]
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _exception_names(element)]
    return []


def _read_name(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _text_reading_helpers(tree: ast.AST) -> set[str]:
    """Functions that decide something from the text of a parameter.

    Moving the comparison into a helper and leaving the parameter unannotated
    was the most natural way around the rule — natural enough that somebody
    would do it without meaning to. Such a helper is treated as a classifier,
    and passing one of our exceptions into it is the finding.
    """
    helpers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        all_args = [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]
        # A parameter annotated as an upstream error is the sanctioned form:
        # the dependency on their wording is declared right in the signature.
        params = {
            arg.arg
            for arg in all_args
            if not any(
                name in UPSTREAM_EXCEPTIONS for name in _exception_names(arg.annotation)
            )
        }
        if not params:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id in {"str", "repr"} and inner.args:
                    if _read_name(inner.args[0]) in params:
                        helpers.add(node.name)
                        break
            if isinstance(inner, ast.Attribute) and inner.attr == "args":
                if _read_name(inner.value) in params:
                    helpers.add(node.name)
                    break
    return helpers


def scan_source(source: str, path: str) -> list[Finding]:
    tree = ast.parse(source)
    scanner = _Scanner(path)
    scanner.text_reading_helpers = _text_reading_helpers(tree)
    scanner.visit(tree)
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
