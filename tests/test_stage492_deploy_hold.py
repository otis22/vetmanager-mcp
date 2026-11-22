"""A stage 492 merge must not trigger an unapproved production cutover."""

from pathlib import Path
import os
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
HOLD = ".github/deploy-hold-stage492"


def test_stage492_merge_holds_automatic_deploy_until_separate_release():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-prod.yml").read_text())
    scope = next(step for step in workflow["jobs"]["changes"]["steps"]
                 if step.get("id") == "scope")["run"]
    freshness = scope.index('if [ "$HEAD_SHA" != "$main_sha" ]')
    hold = scope.index(f"if [ -f {HOLD} ]; then")
    baseline = scope.index('base_sha="$(python3 scripts/deploy_baseline.py)"')
    assert freshness < hold < baseline
    assert 'echo "should_deploy=false" >> "$GITHUB_OUTPUT"' in scope[hold:baseline]
    assert (ROOT / HOLD).is_file()

    classification = subprocess.run(
        ["bash", str(ROOT / "scripts/deploy_scope_check.sh")],
        input=(HOLD + "\0").encode(), capture_output=True, check=True,
    )
    assert classification.stdout.strip() == b"true", "removing the hold must request a deploy"


def test_stage492_deploy_hold_executes_before_baseline_or_staging(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-prod.yml").read_text())
    scope = next(step for step in workflow["jobs"]["changes"]["steps"]
                 if step.get("id") == "scope")["run"]
    marker = tmp_path / HOLD
    marker.parent.mkdir()
    marker.write_text("stage 492 hold\n")
    git = tmp_path / "git"
    git.write_text("#!/bin/sh\n"
                   "[ \"$1\" = rev-parse ] || exit 77\n"
                   "printf '%s\\n' expected-sha\n")
    git.chmod(0o700)
    output = tmp_path / "github-output"
    run = subprocess.run(["bash", "-e", "-c", scope], cwd=tmp_path,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                              "HEAD_SHA": "expected-sha", "GITHUB_OUTPUT": str(output)},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert output.read_text() == "should_deploy=false\n"
    assert "release hold is active" in run.stderr
