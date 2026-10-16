"""Stage 402: retry only a known ECR base-image pull limit."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/retry_ecr_build.sh"
ECR_ERROR = (
    "ERROR: failed to build: failed to solve: failed to resolve source metadata for "
    "public.ecr.aws/docker/library/python:3.12-slim: "
    "toomanyrequests: Data limit exceeded"
)


def _run(tmp_path: Path, responses: list[tuple[int, str]]) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "state = pathlib.Path(os.environ['FAKE_STATE'])\n"
        "calls = int(state.read_text()) if state.exists() else 0\n"
        "state.write_text(str(calls + 1))\n"
        "code, output = json.loads(os.environ['FAKE_RESPONSES'])[min(calls, len(json.loads(os.environ['FAKE_RESPONSES'])) - 1)]\n"
        "print(output, file=sys.stderr)\n"
        "sys.exit(code)\n"
    )
    docker.chmod(0o755)
    sleeper = fake_bin / "sleep"
    sleeper.write_text("#!/bin/sh\nprintf '%s\n' \"$1\" >> \"$FAKE_SLEEPS\"\n")
    sleeper.chmod(0o755)
    state = tmp_path / "calls"
    sleeps = tmp_path / "sleeps"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_STATE": str(state),
        "FAKE_SLEEPS": str(sleeps),
        "FAKE_RESPONSES": json.dumps(responses),
    })
    result = subprocess.run(
        ["bash", str(SCRIPT), "docker", "build", "--target", "test", "."],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    return result, ([state.read_text()] if state.exists() else []), (sleeps.read_text().splitlines() if sleeps.exists() else [])


def test_ecr_429_is_retried_and_logged(tmp_path):
    result, calls, sleeps = _run(tmp_path, [(1, ECR_ERROR), (0, "built")])
    assert result.returncode == 0
    assert calls == ["2"]
    assert sleeps == ["5"]
    assert "attempt 1/3" in result.stdout
    assert "attempt 2/3" in result.stdout
    assert "built" in result.stdout


def test_other_build_failure_is_not_retried(tmp_path):
    result, calls, sleeps = _run(tmp_path, [(23, "Dockerfile RUN pip install failed")])
    assert result.returncode == 23
    assert calls == ["1"]
    assert sleeps == []


def test_unrelated_429_is_not_retried(tmp_path):
    result, calls, sleeps = _run(tmp_path, [(19, "pip returned 429 toomanyrequests: Data limit exceeded")])
    assert result.returncode == 19
    assert calls == ["1"]
    assert sleeps == []


def test_earlier_ecr_error_does_not_retry_later_build_failure(tmp_path):
    output = ECR_ERROR + "\nERROR: failed to solve: Dockerfile RUN pip install failed"
    result, calls, sleeps = _run(tmp_path, [(18, output)])
    assert result.returncode == 18
    assert calls == ["1"]
    assert sleeps == []


def test_ecr_429_stops_after_three_attempts(tmp_path):
    result, calls, sleeps = _run(tmp_path, [(27, ECR_ERROR)])
    assert result.returncode == 27
    assert calls == ["3"]
    assert sleeps == ["5", "15"]


def test_retry_remains_manual_fallback_and_never_wraps_tests():
    for file in ("test.yml", "test-real.yml"):
        workflow = yaml.safe_load((ROOT / ".github/workflows" / file).read_text())
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                assert "retry_ecr_build.sh" not in step.get("run", "")
