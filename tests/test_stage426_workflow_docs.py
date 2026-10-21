"""Guard active workflow instructions against retired review and release commands."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "docs/stage-workflow-template.md",
    ".codex/skills/super-review/SKILL.md",
)
RETIRED = ("/codex rescue", "gpt-5.6-", "-s read-only", "### 9. Codex review")
PUSH_MAIN = re.compile(r"\bgit\s+push\b[^\n`]*(?:\bmain\b|HEAD:main)")
REQUIRED = (
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-6-astra",
    "Claude Opus",
    "scripts/run_claude_review.sh",
    "scripts/validate_review_result.py",
    "dev/",
)


@pytest.mark.parametrize("name", DOCUMENTS)
def test_workflow_docs_require_current_review_and_release_contract(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    for retired in RETIRED:
        assert retired not in text, f"{name} still contains retired instruction: {retired}"
    assert not PUSH_MAIN.search(text), f"{name} instructs pushing to main"
    for required in REQUIRED:
        assert required in text, f"{name} omits current contract: {required}"
    assert "Spark" in text and ("параллельно" in text or "parallel" in text)
    assert "blocked" in text and "infrastructure" in text


def test_release_template_places_both_strong_reviews_before_push():
    text = (ROOT / DOCUMENTS[0]).read_text(encoding="utf-8")
    gate = text.index("Spark-review committed diff → Astra + Claude Opus")
    push = text.index("Push только в назначенную")
    assert gate < push


@pytest.mark.parametrize("command", ("git push origin main", "git push origin HEAD:main", "git push main"))
def test_main_push_guard_catches_command_variants(command):
    assert PUSH_MAIN.search(command)
