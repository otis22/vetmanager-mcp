"""Stage 468: PR checks on dev branches, push checks on main."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_tests_and_docs_run_once_for_dev_pr_and_on_main_push():
    for name in ("test.yml", "docs.yml"):
        workflow = yaml.load(
            (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
        )
        assert workflow["on"]["push"]["branches"] == ["main"], name
        assert workflow["on"]["pull_request"]["branches"] == ["main"], name


def test_other_ci_contours_remain_available():
    shellcheck = yaml.load(
        (ROOT / ".github/workflows/shellcheck.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert shellcheck["on"]["push"]["branches"] == ["main", "dev/**"]
    tests = yaml.load(
        (ROOT / ".github/workflows/test.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert "workflow_dispatch" in tests["on"]
