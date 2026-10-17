"""Stage 414: all relevant CI workflows run on release-train pushes."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_release_train_push_triggers_all_ci_workflows():
    for name in ("test.yml", "shellcheck.yml", "docs.yml"):
        workflow = yaml.load(
            (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
        )
        assert "dev/**" in workflow["on"]["push"]["branches"], name
