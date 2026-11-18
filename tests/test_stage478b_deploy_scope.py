"""Stage 478B-1: strict CI-only deploy scope over the full deployed range."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_scope_check.sh"
CI_PATHS = [
    ".github/workflows/test.yml", ".github/workflows/docs.yml",
    ".github/workflows/shellcheck.yml", ".github/workflows/test-real.yml",
    "scripts/ci_scope.py", "scripts/check_roadmap_structure.py",
    "scripts/offline_gate_manifest.py", "scripts/run_fast_test_suite.py",
    "scripts/run_default_test_suite.py", "scripts/run_isolated_test_suite.py",
    "scripts/run_opt_in_real_test_suite.py", "scripts/default_node_inventory.json",
    "scripts/postgres_node_inventory.json", "scripts/real_group_manifest.json",
    "scripts/offline_integration_files.json", "tests/test_new.py",
]
STAGE_478_6_PATHS = [
    "scripts/ci_test_impact.py", "scripts/test_impact_map.json",
    "scripts/split_default_gate.py", "scripts/run_split_default_suite.py",
    "scripts/nightly_regression.py", "scripts/real_group_gate.py",
    "scripts/prepare_real_test_auth.py", ".github/workflows/nightly.yml",
    "AGENTS.md", "AGENT_ONBOARDING.md", "CLAUDE.md",
]


def decide(raw):
    result = subprocess.run(["bash", str(SCRIPT)], input=raw, capture_output=True, check=True)
    return result.stdout.strip()


@pytest.mark.parametrize("path", CI_PATHS)
def test_explicit_ci_only_paths_do_not_deploy(path):
    assert decide(path.encode() + b"\0") == b"false"


@pytest.mark.parametrize("path", STAGE_478_6_PATHS)
def test_stage478_6_exact_ci_inputs_do_not_deploy(path):
    assert (ROOT / path).is_file()
    assert decide(path.encode() + b"\0") == b"false"


def test_stage478_6_cumulative_docs_ci_only_diff():
    paths = ["README.md", "PRD/этап-478-6-deploy-scope-ci-inputs.md", *STAGE_478_6_PATHS]
    raw = b"\0".join(path.encode() for path in paths) + b"\0"
    assert decide(raw) == b"false"
    for unsafe in ("server.py", "scripts/unknown.py", "docs/../server.md"):
        assert decide(raw + unsafe.encode() + b"\0") == b"true"
    assert decide(raw[:-1]) == b"true"


def test_stage478_6_delete_and_runtime_rename_classify_both_paths():
    # git diff --no-renames emits the deleted path, or both sides of a rename.
    new_path = b"scripts/ci_test_impact.py\0"
    assert decide(new_path) == b"false"
    assert decide(b"server.py\0" + new_path) == b"true"


@pytest.mark.parametrize("path", [
    "unknown.md", "src/README.md", "docs/a.txt", "PRD/payload.py",
    ".github/workflows/unknown.yml", ".github/workflows/deploy-prod.yml",
    "scripts/deploy_scope_check.sh", "scripts/deploy_baseline.py", "scripts/unknown.py",
    "tests/conftest.py", "tests/test_dir/helper.py", "docs/../server.md", "docs//a.md",
    "/docs/a.md", "docs/./a.md", "docs/a\\b.md", "", "server.py",
])
def test_unknown_or_noncanonical_paths_require_deploy(path):
    assert decide(path.encode() + b"\0") == b"true"


@pytest.mark.parametrize("raw", [b"", b"README.md\0server.py", b"README.md\0docs/a.md"])
def test_empty_or_truncated_input_requires_deploy(raw):
    assert decide(raw) == b"true"


def test_cancelled_ci_only_deploy_then_docs_merge_uses_cumulative_range():
    cancelled = b".github/workflows/test.yml\0scripts/offline_gate_manifest.py\0tests/test_new.py\0"
    assert decide(cancelled) == b"false"
    assert decide(cancelled + "PRD/новый.md\0Roadmap.md\0".encode()) == b"false"
    assert decide(cancelled + b"Roadmap.md\0server.py\0") == b"true"


def run_scope(tmp_path, *, stale=False, base="a" * 40, diff_error=False, ancestor=True):
    """Execute the workflow shell; external commands expose deterministic Git/API facts."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-prod.yml").read_text())
    script = next(s["run"] for s in workflow["jobs"]["changes"]["steps"] if s.get("id") == "scope")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "python3": f'print({base!r})\n',
        "git": (
            "import os,sys\na=sys.argv[1:]\n"
            "if a[0]=='rev-parse': print(('c' if os.environ['STALE']=='1' else 'b')*40)\n"
            "elif a[0]=='cat-file': pass\n"
            "elif a[0]=='merge-base': sys.exit(0 if os.environ['ANCESTOR']=='1' else 1)\n"
            "elif 'diff' in a:\n"
            " assert '--no-renames' in a\n"
            " assert 'a'*40 in a and 'b'*40 in a\n"
            " if os.environ['DIFF_ERROR']=='1':\n"
            "  sys.stdout.buffer.write(b'Roadmap.md\\0'); sys.exit(128)\n"
            " sys.stdout.buffer.write(b'.github/workflows/test.yml\\0Roadmap.md\\0')\n"
            "else: sys.exit(99)\n"
        ),
    }.items():
        target = bin_dir / name
        target.write_text(f"#!{sys.executable}\n" + body)
        target.chmod(0o755)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/deploy_scope_check.sh").symlink_to(SCRIPT)
    output = tmp_path / "out"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HEAD_SHA": "b" * 40,
           "GITHUB_OUTPUT": str(output), "STALE": str(int(stale)), "ANCESTOR": str(int(ancestor)),
           "DIFF_ERROR": str(int(diff_error))}
    result = subprocess.run(["bash", "-e", "-c", script],
                            cwd=tmp_path, env=env, capture_output=True)
    return result, output.read_text() if output.exists() else ""


def test_workflow_cumulative_ci_only_diff_skips_deploy(tmp_path):
    result, output = run_scope(tmp_path)
    assert result.returncode == 0, result.stderr
    assert output == "should_deploy=false\n"


@pytest.mark.parametrize("options", [{"diff_error": True}, {"base": ""}])
def test_workflow_lookup_or_diff_error_explicitly_requires_deploy(tmp_path, options):
    result, output = run_scope(tmp_path, **options)
    assert result.returncode == 0, result.stderr
    assert output == "should_deploy=true\n"


@pytest.mark.parametrize("base", ["", "a" * 40])
def test_stale_tests_replay_is_refused_even_without_baseline(tmp_path, base):
    result, output = run_scope(tmp_path, stale=True, base=base)
    assert result.returncode != 0
    assert not output


def test_nonancestor_baseline_is_refused(tmp_path):
    result, output = run_scope(tmp_path, ancestor=False)
    assert result.returncode != 0
    assert not output


def test_success_marker_records_checkout_and_cutover_sha_after_cutover():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-prod.yml").read_text())
    steps = workflow["jobs"]["deploy"]["steps"]
    marker = next(s for s in steps if s.get("name", "").startswith("Record deployed commit "))
    assert marker["name"] == "Record deployed commit ${{ github.event.workflow_run.head_sha }}"
    assert marker["env"]["DEPLOYED_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    assert 'git rev-parse HEAD' in marker["run"]
    assert '"$DEPLOYED_SHA"' in marker["run"]
    assert not marker.get("if") and not marker.get("continue-on-error")
    cutover = next(s for s in steps if s.get("name") == "Run staged maintenance cutover")
    assert steps.index(marker) > steps.index(cutover)
    assert cutover["env"]["GIT_SHA"] == marker["env"]["DEPLOYED_SHA"]
    assert workflow["concurrency"] == {"group": "deploy-prod", "cancel-in-progress": False}
