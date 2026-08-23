"""Stage 254 — documentation-only commits must not rebuild production."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_deploy_workflow_scopes_workflow_run_head_commit_before_deploy() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.head_sha" in text
    assert 'git diff --name-only "${parent_sha}" "${HEAD_SHA}"' in text
    assert "^PRD/|^docs/|\\.md$" in text
    assert "should_deploy=false" in text
    assert "needs.changes.outputs.should_deploy == 'true'" in text


def test_deploy_workflow_keeps_successful_main_workflow_run_gate() -> None:
    text = (REPO_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
