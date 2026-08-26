"""Stage 265.2: the checker that keeps our error messages editable.

A green checker proves nothing on its own — the first version of this one
passed by flagging everything, and the second by flagging nothing. Every case
below is a specimen: known-bad must fail, known-good must not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_error_text_matching.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_error_text_matching", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # The module defines a dataclass, and dataclasses resolve annotations
    # through sys.modules — without registering it first, loading raises.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scan(source: str):
    return _checker().scan_source(source, "specimen.py")


BAD_BRANCHES_ON_OUR_TEXT = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        if "not permitted" in str(exc):
            return "denied"
'''

BAD_READS_ARGS_IN_CONDITION = '''
from exceptions import AuthError

def handle():
    try:
        work()
    except AuthError as exc:
        if exc.args[0].startswith("Bearer"):
            return "denied"
'''

BAD_ANNOTATED_HELPER = '''
from fastmcp.exceptions import ToolError

def classify(exc: ToolError) -> bool:
    return str(exc).lower().startswith("invalid ")
'''

GOOD_SHOWS_THE_TEXT = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        return render(error=str(exc))
'''

GOOD_REDACTS_THE_TEXT = '''
from fastmcp.exceptions import ToolError

def redact(exc: ToolError) -> ToolError:
    return ToolError(*(scrub(value) for value in exc.args))
'''

GOOD_BRANCHES_ON_CODE = '''
from exceptions import AuthError

def handle():
    try:
        work()
    except AuthError as exc:
        if exc.error_code == "scope_denied":
            return "denied"
'''

GOOD_UPSTREAM_CLASSIFIER = '''
from exceptions import VetmanagerError

def _is_retryable(exc: VetmanagerError) -> bool:
    return exc.status_code == 409 and "in progress" in str(exc).lower()
'''

GOOD_NAME_REBOUND_IN_ANOTHER_HANDLER = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        report(str(exc))
    try:
        more()
    except ValueError as exc:
        if "bad" in str(exc):
            return "not ours"
'''


@pytest.mark.parametrize(
    "source",
    [BAD_BRANCHES_ON_OUR_TEXT, BAD_READS_ARGS_IN_CONDITION, BAD_ANNOTATED_HELPER],
)
def test_deciding_on_our_wording_is_reported(source):
    findings = _scan(source)
    assert findings, "the checker must catch a decision made on our own message"


@pytest.mark.parametrize(
    "source",
    [
        GOOD_SHOWS_THE_TEXT,
        GOOD_REDACTS_THE_TEXT,
        GOOD_BRANCHES_ON_CODE,
        GOOD_UPSTREAM_CLASSIFIER,
        GOOD_NAME_REBOUND_IN_ANOTHER_HANDLER,
    ],
)
def test_legitimate_uses_are_left_alone(source):
    assert _scan(source) == [], "showing, redacting and upstream text are all fine"


def test_the_repository_is_clean():
    """The rule is worth nothing if the code it guards already breaks it."""
    module = _checker()
    repo_root = Path(__file__).resolve().parents[1]
    findings = []
    for path in module._tracked_python_files(repo_root):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            findings.extend(module.scan_source(source, str(path.relative_to(repo_root))))
        except SyntaxError:
            continue
    assert findings == [], "\n".join(str(f) for f in findings)


# ── Evasions found by review: none of these are written to dodge the rule, ──
# ── they are just how people naturally write. That is what makes them bad. ──

BAD_VIA_LOCAL_VARIABLE = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        message = str(exc)
        if "not permitted" in message:
            return "denied"
'''

BAD_VIA_FSTRING = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        if "not permitted" in f"{exc}":
            return "denied"
'''

BAD_VIA_PERCENT_FORMAT = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        if "not permitted" in "%s" % exc:
            return "denied"
'''

BAD_VIA_COMPREHENSION = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        return [x for x in [exc] if "not permitted" in str(exc)]
'''

BAD_UPSTREAM_INLINE = '''
from exceptions import VetmanagerError

def handle():
    try:
        work()
    except VetmanagerError as exc:
        if "in progress" in str(exc):
            return "retry"
'''


@pytest.mark.parametrize(
    "source",
    [
        BAD_VIA_LOCAL_VARIABLE,
        BAD_VIA_FSTRING,
        BAD_VIA_PERCENT_FORMAT,
        BAD_VIA_COMPREHENSION,
    ],
)
def test_indirect_routes_to_our_wording_are_reported(source):
    assert _scan(source), "the text reached a decision, however it got there"


def test_upstream_text_inline_is_reported():
    """Upstream text is allowed, but only inside a named classifier.

    Inline in a handler it is invisible: nobody knows the branch depends on a
    sentence Vetmanager may reword.
    """
    findings = _scan(BAD_UPSTREAM_INLINE)
    assert findings, "inline upstream text matching must be pushed into a classifier"


# ── Second round of evasions found by review ────────────────────────────────

BAD_VIA_UNANNOTATED_HELPER = '''
from fastmcp.exceptions import ToolError

def _is_denied(exc):
    return "not permitted" in str(exc)

def handle():
    try:
        work()
    except ToolError as exc:
        if _is_denied(exc):
            return "denied"
'''

BAD_VIA_GETATTR_ARGS = '''
from fastmcp.exceptions import ToolError

def handle():
    try:
        work()
    except ToolError as exc:
        if "not permitted" in getattr(exc, "args")[0]:
            return "denied"
'''

BAD_VIA_CONDITIONAL_ASSIGNMENT = '''
from fastmcp.exceptions import ToolError

def handle(flag):
    try:
        work()
    except ToolError as exc:
        message = str(exc) if flag else ""
        if "not permitted" in message:
            return "denied"
'''

BAD_VIA_STRING_ANNOTATION = '''
def _is_denied(exc: "ToolError") -> bool:
    return "not permitted" in str(exc)
'''


@pytest.mark.parametrize(
    "source",
    [
        BAD_VIA_UNANNOTATED_HELPER,
        BAD_VIA_GETATTR_ARGS,
        BAD_VIA_CONDITIONAL_ASSIGNMENT,
        BAD_VIA_STRING_ANNOTATION,
    ],
)
def test_second_round_of_evasions_is_reported(source):
    assert _scan(source), "the classification still depends on our wording"


GOOD_HELPER_THAT_DOES_NOT_READ_TEXT = '''
from fastmcp.exceptions import ToolError

def _is_denied(exc):
    return getattr(exc, "error_code", None) == "scope_denied"

def handle():
    try:
        work()
    except ToolError as exc:
        if _is_denied(exc):
            return "denied"
'''


def test_a_helper_that_reads_no_text_is_fine():
    """Passing the exception to a helper is normal; reading its wording is not."""
    assert _scan(GOOD_HELPER_THAT_DOES_NOT_READ_TEXT) == []
