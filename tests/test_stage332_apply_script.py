"""Этап 332: production helper validates deployed code before DB writes."""

from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "apply_stage332_known_issues_prod.sh"


def test_apply_requires_deploy_and_preflights_both_configs_before_promote():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "Run only after Deploy Prod of this commit succeeds." in text
    ki45 = (
        "validate-known-issue-config "
        "--match-rules-json /tmp/stage332-ki45-match-rules.json "
        "--playbook-json /tmp/stage332-ki45-playbook.json"
    )
    download = (
        "validate-known-issue-config "
        "--match-rules-json /tmp/stage332-download-401-match-rules.json "
        "--playbook-json /tmp/stage332-download-401-playbook.json"
    )
    promote = "triage_agent_feedback.py promote 80"

    assert text.index(ki45) < text.index(promote)
    assert text.index(download) < text.index(promote)
