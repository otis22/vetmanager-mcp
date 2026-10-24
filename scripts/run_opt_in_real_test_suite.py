#!/usr/bin/env python3
"""Run the opt-in real contour with blocking warnings as errors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_contours import OPT_IN_REAL_TEST_CONTOUR
from warning_policy import build_warning_error_flags


def configuration_errors(env: dict[str, str]) -> list[str]:
    """Reject partial opt-in configuration without exposing values."""
    errors = []
    required_sets = {
        "API key": ("TEST_DOMAIN", "TEST_API_KEY"),
        "login/password": ("TEST_USER_TOKEN_BASE_URL", "TEST_USER_LOGIN", "TEST_USER_PASSWORD"),
        "stage 385 isolated": ("STAGE385_REDIS_URL", "STAGE385_PG_URL", "STAGE385_PG_HOOK_DIR"),
    }
    for name, keys in required_sets.items():
        if name == "API key":
            continue  # TEST_DOMAIN can also belong to a complete user-token contour.
        present = [key for key in keys if env.get(key)]
        if present and len(present) != len(keys):
            errors.append(f"{name}: incomplete configuration; required: {', '.join(keys)}")
    if env.get("TEST_API_KEY") and not env.get("TEST_DOMAIN"):
        errors.append("API key: TEST_DOMAIN is required")
    if env.get("TEST_DOMAIN") and not any((
        env.get("TEST_API_KEY"), env.get("TEST_USER_TOKEN"),
        all(env.get(key) for key in required_sets["login/password"]),
    )):
        errors.append("TEST_DOMAIN requires an API key or user-token configuration")
    if env.get("TEST_USER_TOKEN") and not env.get("TEST_DOMAIN"):
        errors.append("direct user token: TEST_DOMAIN is required")
    if env.get("RUN_REAL_WEB_TESTS") == "1" and not all(env.get(key) for key in required_sets["API key"]):
        errors.append("web flow: TEST_DOMAIN and TEST_API_KEY are required")
    browser_enabled = env.get("RUN_REAL_BROWSER_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}
    if browser_enabled and not all(env.get(key) for key in required_sets["API key"]):
        errors.append("browser API-key flow: TEST_DOMAIN and TEST_API_KEY are required")
    if env.get("STAGE400_PG_URL") and not all(env.get(key) for key in required_sets["API key"]):
        errors.append("stage 400: TEST_DOMAIN and TEST_API_KEY are required")
    if any(env.get(key) for key in required_sets["stage 385 isolated"]) and not all(
        env.get(key) for key in required_sets["API key"]
    ):
        errors.append("stage 385: TEST_DOMAIN and TEST_API_KEY are required")
    return errors


def contour_inventory(env: dict[str, str]) -> dict[str, bool]:
    return {
        "api-key": bool(env.get("TEST_DOMAIN") and env.get("TEST_API_KEY")),
        "direct-user-token": bool(env.get("TEST_USER_TOKEN")),
        "login-password-token": bool(env.get("TEST_USER_TOKEN_BASE_URL") and env.get("TEST_USER_LOGIN") and env.get("TEST_USER_PASSWORD")),
        "web-account": env.get("RUN_REAL_WEB_TESTS") == "1",
        "real-browser-api-key": env.get("RUN_REAL_BROWSER_TESTS", "").strip().lower() in {"1", "true", "yes", "on"} and bool(env.get("TEST_DOMAIN") and env.get("TEST_API_KEY")),
        "real-browser-user-token": env.get("RUN_REAL_BROWSER_TESTS", "").strip().lower() in {"1", "true", "yes", "on"} and bool(env.get("TEST_USER_TOKEN_BASE_URL") and env.get("TEST_USER_LOGIN") and env.get("TEST_USER_PASSWORD")),
        "stage385-isolated": bool(env.get("STAGE385_REDIS_URL") and env.get("STAGE385_PG_URL") and env.get("STAGE385_PG_HOOK_DIR") and env.get("TEST_DOMAIN") and env.get("TEST_API_KEY")),
        "stage400-postgres": bool(env.get("STAGE400_PG_URL")),
    }


def read_outcome(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = data["counts"]
    if data["collected"] < 1 or any(
        not isinstance(counts[key], int) or counts[key] < 0
        for key in ("passed", "failed", "skipped-not-configured", "skipped-error")
    ) or sum(counts.values()) < data["collected"]:
        raise ValueError("invalid or empty real test outcome")
    return data


def main() -> int:
    warning_flags = [item for flag in build_warning_error_flags() for item in ("-W", flag)]
    base_command = [
        sys.executable,
        *warning_flags,
        "-m",
        "pytest",
        "-p",
        "tests.real_suite_outcomes",
        "-v",
        "-m",
        OPT_IN_REAL_TEST_CONTOUR.marker_expression,
    ]
    env = dict(os.environ)
    env.setdefault("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", "0.5")
    errors = configuration_errors(env)
    if errors:
        for error in errors:
            print(f"real suite configuration error: {error}", file=sys.stderr)
        return 2
    for name, configured in contour_inventory(env).items():
        print(f"real contour {name}: {'live' if configured else 'dead (not configured)'}", flush=True)
    commands = [
        [
            *base_command,
            "tests/",
            "-k",
            "not test_real_web_account_can_issue_bearer_and_call_tool",
        ],
        [
            *base_command,
            "tests/test_e2e_real.py::test_real_web_account_can_issue_bearer_and_call_tool",
        ],
    ]
    totals = {key: 0 for key in ("passed", "failed", "skipped-not-configured", "skipped-error")}
    failed = False
    with tempfile.TemporaryDirectory(prefix="real-suite-outcomes-") as temp_dir:
        for index, command in enumerate(commands, 1):
            path = Path(temp_dir) / f"group-{index}.json"
            path.unlink(missing_ok=True)
            env["PYTEST_REAL_OUTCOME_FILE"] = str(path)
            completed = subprocess.run(command, env=env, check=False)
            if completed.returncode != 0:
                failed = True
            try:
                outcome = read_outcome(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"real suite group {index}: missing/invalid outcome ({type(exc).__name__})", file=sys.stderr)
                failed = True
                continue
            for key in totals:
                totals[key] += outcome["counts"][key]
            print(f"real suite group {index}: collected={outcome['collected']} "
                  + " ".join(f"{key}={outcome['counts'][key]}" for key in totals), flush=True)
            for nodeid in outcome["not_configured"]:
                print(f"skipped-not-configured: {nodeid}", flush=True)
            for nodeid in outcome["skip_errors"]:
                print(f"skipped-error: {nodeid}", flush=True)
            if outcome["counts"]["failed"] or outcome["counts"]["skipped-error"]:
                failed = True
    print("real suite total: " + " ".join(f"{key}={value}" for key, value in totals.items()), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
