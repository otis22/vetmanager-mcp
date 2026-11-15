"""Stage 465 guard for the Docker Compose oracle on a Docker-capable host."""

from pathlib import Path

import yaml


def test_stage190_compose_validator_is_mandatory_in_ci() -> None:
    script = Path("scripts/check_stage190_compose.py")
    assert script.is_file()
    workflow = yaml.safe_load(Path(".github/workflows/test.yml").read_text())
    steps = workflow["jobs"]["default"]["steps"]
    matches = [step for step in steps if "python3 scripts/check_stage190_compose.py" in step.get("run", "")]
    assert len(matches) == 1
    assert not matches[0].get("if")
    assert not matches[0].get("continue-on-error")
