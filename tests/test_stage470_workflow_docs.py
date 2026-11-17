"""Stage 470: workflow wording agrees with contour invalidation."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("name", [
    "AGENTS.md", "CLAUDE.md", ".cursor/rules/agent-workflow.mdc",
    "docs/stage-workflow-template.md",
])
def test_workflow_names_real_only_exception_and_current_gate(name):
    text = Path(name).read_text(encoding="utf-8")
    assert "real-only test — только real" in text
    assert "после правки runtime/tests" not in text
    assert "до этапа 469" not in text
    assert "общий fingerprint" not in text


def test_stage461_heading_is_level_two_and_separated():
    text = Path("AssumptionLog.md").read_text(encoding="utf-8")
    assert "\n\n## Этап 461 — предварительная диагностика" in text
    assert "\n# Этап 461 — предварительная диагностика" not in text
