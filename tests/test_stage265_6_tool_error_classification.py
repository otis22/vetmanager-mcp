"""Stage 265.6: inside `tools/`, a `ToolError` is never built by hand.

Two names carry the classification instead, and they say it in the same line
where the refusal is written:

    ToolInputError(...)   — the caller got an argument wrong
    reportable_error(...) — everything else: upstream, its broken payload, us

The first draft of this guard kept an inventory of `raise ToolError` sites.
External PRD review broke it twice over: three factories in this repository
already *return* a ToolError instead of raising it, and an inventory keyed on
counts stays green when one check is retyped while another is added next to it.
A rule with no exceptions has neither hole.

Every specimen below is written the way somebody would write it naturally —
not to dodge the rule, just because it reads fine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_tool_error_classification.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_tool_error_classification", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # The module defines a dataclass, and dataclasses resolve annotations
    # through sys.modules — without registering it first, loading raises.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


KNOWN_BAD = {
    "raised_directly": """
from fastmcp.exceptions import ToolError

def check(value):
    if value <= 0:
        raise ToolError("value must be a positive integer.")
""",
    "returned_by_a_factory": """
from fastmcp.exceptions import ToolError

def _input_error(name) -> ToolError:
    return ToolError(f"{name} must be a positive integer.")

def check(value):
    if value <= 0:
        raise _input_error("value")
""",
    "held_in_a_local_first": """
from fastmcp.exceptions import ToolError

def check(value):
    if value <= 0:
        error = ToolError("value must be a positive integer.")
        raise error
""",
    "imported_under_another_name": """
from fastmcp.exceptions import ToolError as TE

def check(value):
    if value <= 0:
        raise TE("value must be a positive integer.")
""",
    "called_through_the_module": """
import fastmcp.exceptions as fastmcp_exceptions

def check(value):
    if value <= 0:
        raise fastmcp_exceptions.ToolError("value must be a positive integer.")
""",
    "called_through_a_module_alias": """
from fastmcp import exceptions as fastmcp_exceptions

def check(value):
    if value <= 0:
        raise fastmcp_exceptions.ToolError("value must be a positive integer.")
""",
    "rebound_to_another_name": """
from fastmcp.exceptions import ToolError

_ERROR = ToolError

def check(value):
    if value <= 0:
        raise _ERROR("value must be a positive integer.")
""",
    "a_bare_value_error": """
def check(value):
    if value <= 0:
        raise ValueError("value must be a positive integer.")
""",
    "a_value_error_through_builtins": """
import builtins

def check(value):
    if value <= 0:
        raise builtins.ValueError("value must be a positive integer.")
""",
    "a_value_error_under_another_name": """
_ERROR = ValueError

def check(value):
    if value <= 0:
        raise _ERROR("value must be a positive integer.")
""",
    "imported_as_a_package_alias": """
import fastmcp as fm

def check(value):
    if value <= 0:
        raise fm.exceptions.ToolError("value must be a positive integer.")
""",
    "imported_as_a_deep_module_alias": """
import fastmcp.exceptions as fastmcp_exceptions

def check(value):
    if value <= 0:
        raise fastmcp_exceptions.ToolError("value must be a positive integer.")
""",
    "rebound_with_a_type_annotation": """
from fastmcp.exceptions import ToolError

_ERROR: type[Exception] = ToolError

def check(value):
    if value <= 0:
        raise _ERROR("value must be a positive integer.")
""",
    "rebound_by_a_walrus": """
from fastmcp.exceptions import ToolError

def check(value):
    if value <= 0 and (error_cls := ToolError):
        raise error_cls("value must be a positive integer.")
""",
    "built_inside_a_comprehension": """
from fastmcp.exceptions import ToolError

def check(values):
    problems = [ToolError(f"{v} is not allowed.") for v in values if v < 0]
    if problems:
        raise problems[0]
""",
}

KNOWN_GOOD = {
    "the_callers_mistake": """
from exceptions import ToolInputError

def check(value):
    if value <= 0:
        raise ToolInputError("value must be a positive integer.")
""",
    "worth_reporting": """
from exceptions import reportable_error

def check(payload):
    if not payload.get("data"):
        raise reportable_error("Vetmanager returned no data for this request.")
""",
    "catching_is_not_building": """
from fastmcp.exceptions import ToolError

def run(call):
    try:
        return call()
    except ToolError:
        raise
""",
    "annotating_is_not_building": """
from fastmcp.exceptions import ToolError
from exceptions import reportable_error

def translate(exc) -> ToolError | None:
    if exc.status_code == 500:
        return reportable_error("Upstream failed.")
    return None
""",
    "another_class_from_the_same_package": """
import fastmcp as fm

def build():
    return fm.FastMCP(name="vetmanager")
""",
    "an_invariant_says_so": """
from exceptions import invariant_error

def split(total, parts):
    if parts <= 0:
        raise invariant_error("parts must be positive; the caller cannot reach this.")
""",
    "catching_a_value_error_is_not_building": """
def parse(text):
    try:
        return int(text)
    except ValueError:
        return None
""",
    "asking_the_type_is_not_building": """
from fastmcp.exceptions import ToolError

def is_ours(exc) -> bool:
    return isinstance(exc, ToolError)
""",
}


@pytest.mark.parametrize("name", sorted(KNOWN_BAD))
def test_known_bad_specimen_is_caught(tmp_path, name):
    module = _load()
    path = tmp_path / "tools" / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(KNOWN_BAD[name], encoding="utf-8")
    assert module.scan_paths([path]), f"specimen {name} passed the guard"


@pytest.mark.parametrize("name", sorted(KNOWN_GOOD))
def test_known_good_specimen_is_left_alone(tmp_path, name):
    module = _load()
    path = tmp_path / "tools" / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(KNOWN_GOOD[name], encoding="utf-8")
    assert module.scan_paths([path]) == [], f"specimen {name} was flagged"


def test_the_repository_itself_is_clean():
    module = _load()
    root = Path(__file__).resolve().parents[1]
    findings = module.scan_paths([root / "tools", root / "validators.py"])
    assert findings == [], "\n".join(str(f) for f in findings)
