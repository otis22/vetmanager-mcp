"""Stage 254 — documentation-only commits must not rebuild production."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_deploy_workflow_scopes_from_last_successful_deploy_before_deploy() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.head_sha" in text
    assert "python3 scripts/deploy_baseline.py" in text
    baseline = (REPO_ROOT / "scripts/deploy_baseline.py").read_text(encoding="utf-8")
    assert "/actions/workflows/deploy-prod.yml/runs" in baseline
    assert 'job.get("name") == "deploy"' in baseline
    assert 'job.get("conclusion") == "success"' in baseline
    # Stage 254.3: these two lines used to pin the exact escaping-prone call
    # (`git diff --name-only` plus a regex over its output), so the test stayed
    # green while a Russian-named PRD walked straight through the filter. The
    # contract is now the raw-path form and the shared decision script.
    assert "git -c core.quotepath=false diff --name-only -z" in text
    assert "./scripts/deploy_scope_check.sh" in text
    assert "fetch-depth: 0" in text
    # The verdict itself now comes from the script, so the workflow only has
    # to hand it through unchanged.
    assert 'echo "should_deploy=${should_deploy}"' in text
    assert "needs.changes.outputs.should_deploy == 'true'" in text


def test_deploy_workflow_fails_open_when_no_successful_deploy_baseline_is_available() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert 'if [ -z "${base_sha}" ]; then' in text
    assert "Never silently skip a deploy" in text


def test_deploy_workflow_keeps_successful_main_workflow_run_gate() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
