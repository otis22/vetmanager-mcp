"""Stage 254 — documentation-only commits must not rebuild production."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_deploy_workflow_scopes_from_last_successful_deploy_before_deploy() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.head_sha" in text
    assert "actions/workflows/deploy-prod.yml/runs?branch=main&status=completed" in text
    assert '.name == "deploy" and .conclusion == "success"' in text
    assert 'git diff --name-only "${base_sha}" "${HEAD_SHA}"' in text
    assert "fetch-depth: 0" in text
    assert "^PRD/|^docs/|\\.md$" in text
    assert "should_deploy=false" in text
    assert "needs.changes.outputs.should_deploy == 'true'" in text


def test_deploy_workflow_fails_open_when_no_successful_deploy_baseline_is_available() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert 'if [ -z "${base_sha}" ]; then' in text
    assert "Never silently skip a deploy" in text


def test_deploy_workflow_keeps_successful_main_workflow_run_gate() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
